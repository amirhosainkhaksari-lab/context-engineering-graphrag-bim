import ifcopenshell
import ifcopenshell.util.element as el
import re
import ifcopenshell.util.unit
import ifcopenshell.geom
import numpy as np
import collections
from neo4j import GraphDatabase
import json
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import SentenceTransformer
import torch


ifc_file = ifcopenshell.open("-")

unit_scale = 1.0
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)

settings = ifcopenshell.geom.settings()
settings.set(settings.DISABLE_OPENING_SUBTRACTIONS, True)    
settings.set(settings.USE_WORLD_COORDS, True)

spatial_types={
    "IfcProject",
    "IfcSite",
    "IfcBuilding",
    "IfcBuildingStorey",
    "IfcSpace"}

EXCLUDED_CLASSES = {
    'IfcAnnotation',     
    'IfcStructuralItem', 
    'IfcPort',          
    'IfcDistributionElement', 
    'IfcReinforcingElement',  
    'IfcFastener',
    'IfcFurniture',
    'IfcFurnishingElement'}

#=================================================================================================================
def extract_spatialhierarchy(ifc_file):
    
    nodes = {}
    edges = []

    
    for project in ifc_file.by_type("IfcProject"):
        
        length_unit_name = "UNKNOWN"
        if project.UnitsInContext and project.UnitsInContext.Units:
            for unit in project.UnitsInContext.Units:
                if unit.is_a("IfcNamedUnit") and unit.UnitType == "LENGTHUNIT":
                    prefix = unit.Prefix if hasattr(unit, "Prefix") and unit.Prefix else ""
                    length_unit_name = f"{prefix}{unit.Name}"
                    break
                    
        nodes[project.GlobalId] = {
            "guid": project.GlobalId,
            "ifc_id": project.id(), 
            "name": project.Name or project.is_a(),
            "label": project.is_a(),
            "type": project.is_a(),
            "description": project.Description if hasattr(project,"Description") else None,
            "predefined_type": None,
            "unit_scale": unit_scale,
            "length_unit_name":length_unit_name}

        
    for product in ifc_file.by_type("IfcProduct"):

        if product.is_a() in EXCLUDED_CLASSES:
            continue

            
        product_name = product.Name or product.is_a()

        if product.is_a("IfcSpace"):
            long_name = product.LongName if hasattr(product, "LongName") and product.LongName else ""
            exact_name = f"{product.Name or ''} - {long_name}".strip(' -') or product.GlobalId
            
                
        desc = product.Description if hasattr(product,"Description") else None
        predefined_type = product.PredefinedType if hasattr(product,"PredefinedType") else None
        
        if product.GlobalId not in nodes:
            nodes[product.GlobalId] = {
                "guid": product.GlobalId,
                "ifc_id": product.id(), 
                "name": product_name,
                "label": product.is_a(),
                "type": product.is_a(),
                "description": desc,
                "predefined_type": predefined_type,
                "global_centroid": None,
                "bbox_dimensions": None,
                "intrinsic_dimensions": {},
                "unit_scale": unit_scale }

       
#=============================================================================================

        if hasattr(product,"LongName") and product.LongName:
            if nodes[product.GlobalId]["name"] != "Stair":
                nodes[product.GlobalId]["name"] = product.LongName
            
        if hasattr(product, "OverallWidth") and product.OverallWidth is not None:
            nodes[product.GlobalId]["intrinsic_dimensions"]["OverallWidth"] = product.OverallWidth * unit_scale
    
        if hasattr(product, "OverallHeight") and product.OverallHeight is not None:
            nodes[product.GlobalId]["intrinsic_dimensions"]["OverallHeight"] = product.OverallHeight * unit_scale
    
        if hasattr(product, "OverallLength") and product.OverallLength is not None:
            nodes[product.GlobalId]["intrinsic_dimensions"]["OverallLength"] = product.OverallLength * unit_scale
    
        if hasattr(product, "Length") and product.Length is not None:
            nodes[product.GlobalId]["intrinsic_dimensions"]["Length"] = product.Length * unit_scale

        
        if not nodes[product.GlobalId]["intrinsic_dimensions"]:
            nodes[product.GlobalId].pop("intrinsic_dimensions")
#=====================================================================================================                       

        has_valid_geom = False
        
        if hasattr(product, "Representation") and product.Representation and hasattr(product.Representation, "Representations"):
            for rep in product.Representation.Representations:
                if hasattr(rep, "Items") and rep.Items:
                    has_valid_geom = True
                    break
    
        if has_valid_geom:
            shape = None
        
            shape = ifcopenshell.geom.create_shape(settings,product)
            
            if shape and hasattr(shape, "geometry") and hasattr(shape.geometry, "verts") and shape.geometry.verts:
                verts = np.array(shape.geometry.verts).reshape((-1, 3)) * unit_scale
                min_c = verts.min(axis=0)
                max_c = verts.max(axis=0)
                centroid = (min_c + max_c) / 2.0
                dims = max_c - min_c
    
                nodes[product.GlobalId]["global_centroid"] = centroid.tolist()
                nodes[product.GlobalId]["bbox_dimensions"] = dims.tolist()

        
        if not nodes[product.GlobalId]["global_centroid"]:
            nodes[product.GlobalId].pop("global_centroid")

        if not nodes[product.GlobalId]["bbox_dimensions"]:
            nodes[product.GlobalId].pop("bbox_dimensions")
        
           
# =============================================================================================   

    boundaries = ifc_file.by_type("IfcRelSpaceBoundary")

    seen_boundaries = set()
    
    for bnd in boundaries:
        space = bnd.RelatingSpace
        element = bnd.RelatedBuildingElement
        
        if space and (space.GlobalId in nodes):
            if element and (element.GlobalId in nodes):
                space_guid = space.GlobalId
                el_guid = element.GlobalId
                
                if (space_guid, el_guid) in seen_boundaries:
                    continue
                seen_boundaries.add((space_guid, el_guid))
                
                bnd_type = bnd.PhysicalOrVirtualBoundary if hasattr(bnd, "PhysicalOrVirtualBoundary") else "UNKNOWN"
                
                edges.append({
                    "from": space_guid,
                    "to": el_guid,
                    "label": "BOUNDED_BY",
                    "boundary_type": bnd_type, 
                    "rel_guid": bnd.GlobalId,
                    "rel_ifc_id": bnd.id(),
                    "rel_type": bnd.is_a()
                })

    edges = [edge for edge in edges if edge["from"] in nodes and edge["to"] in nodes]
    
#=====================================================================    
        
    rels = ifc_file.by_type("IfcRelAggregates")

    for rel in rels:
        
        parent = rel.RelatingObject        
                        
        for child in rel.RelatedObjects:
          
            if parent.GlobalId in nodes and child.GlobalId in nodes:
                
                if parent.is_a() in spatial_types:
                    
                    edge_label = "SPATIAL_AGGREGATES"
                else:
                    edge_label = "DETAILS_AGGREGATES"
    
                edges.append({
                    "from":parent.GlobalId,
                    "to": child.GlobalId,
                    "label": edge_label,
                    "rel_guid": rel.GlobalId,
                    "rel_ifc_id": rel.id(),
                    "rel_type": rel.is_a()})


    rels = ifc_file.by_type("IfcRelContainedInSpatialStructure")
    
    for rel in rels:
        
        parent = rel.RelatingStructure
        children = rel.RelatedElements

        for child in children:
           
            if parent.GlobalId in nodes and child.GlobalId  in nodes:
               
                edges.append({
                    "from":parent.GlobalId,
                    "to":child.GlobalId,
                    "label":"CONTAINS_ELEMENTS",
                    "rel_guid": rel.GlobalId,
                    "rel_ifc_id": rel.id(),
                    "rel_type": rel.is_a()})

#=============================================================================================   
            
    rels_voids = ifc_file.by_type("IfcRelVoidsElement")
    for rel in rels_voids:
        parent_element = rel.RelatingBuildingElement
        opening = rel.RelatedOpeningElement
        if opening.GlobalId in nodes and parent_element.GlobalId in nodes:
            edges.append({
                    "from": parent_element.GlobalId,
                    "to": opening.GlobalId,
                    "label": "HAS_OPENING",
                    "rel_guid": rel.GlobalId,
                    "rel_ifc_id": rel.id(),
                    "rel_type": rel.is_a() })
            
    rels_fills = ifc_file.by_type("IfcRelFillsElement")
    for rel in rels_fills:
        opening = rel.RelatingOpeningElement
        element = rel.RelatedBuildingElement
        
        if opening.GlobalId in nodes and element.GlobalId in nodes :
            edges.append({
                "from": opening.GlobalId,
                "to": element.GlobalId,
                "label": "FILLED_BY",
                "rel_guid": rel.GlobalId,
                "rel_ifc_id": rel.id(),
                "rel_type": rel.is_a() })

#=============================================================================================    
    rels = ifc_file.by_type("IfcRelDefinesByProperties")
    
    for rel in rels:
        
        pset = rel.RelatingPropertyDefinition
      
        if isinstance(pset,list):
            psets = pset
        else:
            psets = [pset]
        
        for pset in psets:
            pset_name = pset.Name or pset.is_a()
            
            key = re.sub(r'[^a-z0-9]+', '', pset_name.lower())
    
            if pset.GlobalId not in nodes:
             
                nodes[pset.GlobalId]={
                    "guid": pset.GlobalId,
                    "ifc_id": pset.id(),
                    "name": pset_name,
                    "label": pset.is_a(),
                    "type": pset.is_a(),
                    "properties":{} }

            elements = rel.RelatedObjects
            
            for element in elements:
               
                if element.GlobalId in nodes:
                    
                    edges.append({
                        "from": element.GlobalId,
                        "to": pset.GlobalId,
                        "label": "HAS_PROPERTYSETS",
                        "rel_guid": rel.GlobalId,
                        "rel_ifc_id": rel.id(),
                        "rel_type": rel.is_a() })

                if hasattr(pset,"HasProperties") and pset.HasProperties:
                    props = pset.HasProperties
                    
                    for i,prop in enumerate(props):
                        prop_name = prop.Name or f"prop_{i}"
                        prop_id = f"{pset.GlobalId}_{prop_name}_{i}"
    
                        if prop.is_a("IfcPropertySingleValue")  :
                            val = None
                            value_type = None
                            
                            if prop.NominalValue is not None:
                                value_type = prop.NominalValue.is_a()
                                
                                if  hasattr(prop.NominalValue,"wrappedValue"): 
                                    val = prop.NominalValue.wrappedValue
                                else:
                                    val = prop.NominalValue                               

                            unit = prop.Unit.Name if hasattr(prop,"unit") and prop.Unit else "" 
                            key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())

                            if val:
                                nodes[pset.GlobalId]["properties"][prop_name]= f"{val} {unit}".strip()
                                  
                                 
                        elif prop.is_a("IfcPropertyListValue"):
                            prop_list = prop.ListValues
                            vals=[]
                            value_type = None
                            
                            if prop_list:
                                for p in prop_list:
                                    if value_type is None:
                                        value_type = p.is_a()
                                        
                                    if hasattr(p,"wrappedValue"):
                                        vals.append(str(p.wrappedValue))
                                    else:
                                        vals.append(str(p))
                            else:
                                vals=None
                                value_type = None
                            
                            
                            key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
                            unit = prop.Unit.Name if hasattr(prop,"Unit") and prop.Unit else ""

                            if vals:
                                joined_vals = ",".join(vals)
                                nodes[pset.GlobalId]["properties"][prop_name]= f"{joined_vals} {unit}".strip()
                                    
                                       
                        elif prop.is_a("IfcPropertyEnumeratedValue"):
                            prop_enu = prop.EnumerationValues
                            vals =[]
                            value_type = None
                            
                            if prop_enu :
                                for p in prop_enu:
                                    
                                    if value_type is None:
                                        value_type = p.is_a()
                                        
                                    if hasattr(p,"wrappedValue"):
                                        vals.append(str(p.wrappedValue))
                                    else:
                                        vals.append(str(p))
                            else:
                                vals=None
                                value_type = None
     
                            key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
                            unit = prop.Unit.Name if hasattr(prop,"Unit") and prop.Unit else ""

                            if vals:
                                joined_vals = ",".join(vals)   
                                nodes[pset.GlobalId]["properties"][prop_name]= f"{joined_vals} {unit}".strip()
                                    
                                
                        elif prop.is_a("IfcPropertyBoundedValue"):
                            value_type = None
                            lo = None
                            up = None
                            
                            if prop.LowerBoundValue is not None:
                                value_type = prop.LowerBoundValue.is_a()
                                if hasattr(prop.LowerBoundValue,"wrappedValue"):
                                    lo = prop.LowerBoundValue.wrappedValue
                                    if isinstance(lo,(int,float)):
                                        lo = str(float(lo))
                                else:
                                    lo = str(prop.LowerBoundValue)          
                            
                            if prop.UpperBoundValue is not None:
                                if value_type is None:
                                    value_type = prop.UpperBoundValue.is_a()
                                if hasattr(prop.UpperBoundValue,"wrappedValue"):
                                    up = prop.UpperBoundValue.wrappedValue
                                    if isinstance(up,(int,float)):
                                        up = str(float(up))
                                else:
                                    up = str(prop.UpperBoundValue)
        
                                  
                            key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
                            unit = prop.Unit.Name if hasattr(prop,"Unit") and prop.Unit else ""

                            if lo and up:     
                                nodes[pset.GlobalId]["properties"][prop_name]= f"{lo}{unit}<{up}{unit}"
                                   
                                       
                        elif prop.is_a("IfcComplexProperty"):
                            prop_complex = prop.HasProperties
                            
                            key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
            
                            for i,sub in enumerate(prop_complex):
                                sub_name = f"{prop_name}_{sub.Name}" or f"sub_{i}"
                                sub_id = f"{prop_id}_{sub_name}_{i}"
                                
                                if sub.is_a("IfcPropertySingleValue"):
                                    sval = None
                                    value_type = None
                                    
                                    if sub.NominalValue is not None:
                                        value_type = sub.NominalValue.is_a()
                                        
                                        if hasattr(sub.NominalValue,"wrappedValue"):
                                            sval = sub.NominalValue.wrappedValue
                                        else:
                                            sval = str(sub.NominalValue)
                                    else:
                                        sval = None
                                        value_type = None


                                    key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                    unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""
                                    
                                    nodes[pset.GlobalId]["properties"]["sub_names"] = f"{sval} {unit}".strip()
                                         

                                elif sub.is_a("IfcPropertyListValue"):
                                    sub_list = sub.ListValues
                                    vals=[]
                                    value_type = None
                                    
                                    if sub_list:
                                        for s in sub_list:
                                            if value_type is None:
                                                value_type = s.is_a()
                                            
                                            if hasattr(s, "wrappedValue"):
                                                vals.append(str(s.wrappedValue))
                                            else:
                                                vals.append(str(s))
                                    else:
                                        vals = None
                                        value_type = None
                                    

                                    key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                    unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""

                                    if vals:
                                        joined_vals = ",".join(vals)
                                        nodes[pset.GlobalId]["properties"]["sub_names"]= f"{joined_vals} {unit}".strip()
                                           
                                                    
                                elif sub.is_a("IfcPropertyEnumeratedValue"):
                                    sub_enu = sub.EnumerationValues
                                    vals=[]
                                    value_type = None
                                    
                                    if sub_enu :
                                        for s in sub_enu:
                                            if value_type is None:
                                                value_type = s.is_a()
                                            
                                            if hasattr(s,"wrappedValue"):
                                                vals.append(str(s.wrappedValue))
                                            else:
                                                vals.append(str(s))
                                    else:
                                        vals = None
                                        value_type = None
                                    

                                    key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                    unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""

                                    if vals:
                                        nodes[pset.GlobalId]["properties"]["sub_names"]= f"{joined_vals} {unit}".strip() 
                                
                                elif sub.is_a("IfcPropertyBoundedValue"):
                                    value_type = None
                                    
                                    if sub.LowerBoundValue is not None:
                                        value_type = sub.LowerBoundValue.is_a()
                                        
                                        if hasattr(sub.LowerBoundValue,"wrappedValue"):
                                            lo = sub.LowerBoundValue.wrappedValue
                                            if isinstance(lo , (int,float)):
                                                lo = float(lo)
                                        else:
                                            lo = sub.LowerBoundValue
                                    else:
                                        lo = None
                                        value_type = None
                                    
                                    if sub.UpperBoundValue is not None:
                                        if value_type is None:
                                            value_type = sub.UpperBoundValue.is_a()
                                        else:
                                            value_type = None
                                            
                                        if hasattr(sub.UpperBoundValue,"wrappedValue"):
                                            up = sub.UpperBoundValue.wrappedValue
                                            if isinstance(up , (int,float)):
                                                up = float(up)
                                        else:
                                            up = sub.UpperBoundValue
                                    else:
                                        up = None
                                        value_type = None

                                    key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                    unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""

                                    if lo and up:
                                        nodes[pset.GlobalId]["properties"]["sub_names"] = f"{lo}{unit}<{up}{unit}"
                                            
                            
                elif pset.is_a("IfcPreDefinedPropertySet"):

                    nodes[pset.GlobalId].pop("properties",None)
                    el_info = pset.get_info()
                    ignored_keys = ["id","GlobalId","Name","Description","Type","OwnerHistory"]
                    
                    for key,value in el_info.items():
                        if key in ignored_keys or value in [ None,[],{},""]:
                            continue
                        nodes[pset.GlobalId][key] = value
                   
        
                elif hasattr(pset,"Quantities") and pset.Quantities:
                    qtys = pset.Quantities
                
                    for i, qty in enumerate(qtys):
                        qty_name = qty.Name or f"qty_{i}"
                        qty_id = f"{pset.GlobalId}_{qty_name}_{i}"
                        val = None
                        value_type = None
                        unit_str = None
                        
                        if qty.is_a("IfcQuantityLength"):
                            if hasattr(qty,"LengthValue") and qty.LengthValue is not None:
                                val = float(qty.LengthValue) * unit_scale
                                unit_str = "m"
                                
                        if qty.is_a("IfcQuantityArea"):
                            if hasattr(qty,"AreaValue") and qty.AreaValue is not None:
                                val = float(qty.AreaValue) 
                                unit_str = "m^2"
                                
                        if qty.is_a("IfcQuantityVolume"):
                            if hasattr(qty,"VolumeValue") and qty.VolumeValue is not None :
                                val = float(qty.VolumeValue) 
                                unit_str = "m^3"
                                
                        if qty.is_a("IfcQuantityWeight"):
                            if hasattr(qty,"WeightValue") and qty.WeightValue is not None:
                                val = float(qty.WeightValue)
                                unit_str = qty.Unit.Name if hasattr(qty,"Unit") and qty.Unit else None
                        
                        if qty.is_a("IfcQuantityCount"):
                            if hasattr(qty,"CountValue") and qty.CountValue is not None:
                                val = float(qty.CountValue)
                                unit_str = qty.Unit.Name if hasattr(qty,"Unit") and qty.Unit else None
                                
                        if qty.is_a("IfcQuantityTime"):
                            if hasattr(qty,"TimeValue") and qty.TimeValue is not None:
                                val = float(qty.TimeValue)
                                unit_str = qty.Unit.Name if hasattr(qty,"Unit") and qty.Unit else None
                
                        qty_type = qty.is_a()
                        if qty_type == "IfcQuantityWeight":
                            value_type = "IfcMassMeasure"
                        else:
                            qty_type = qty_type.replace("IfcQuantity", "Ifc")
                            value_type = f"{qty_type}" + "Measure"
                
                        
                        key = re.sub(r'[^a-z0-9]+', '', qty_name.lower())
                        
                        nodes[pset.GlobalId]["properties"][qty_name] = f"{val}{unit_str}"
                                                         
#==========================================================================    
                 
    rels = ifc_file.by_type("IfcRelDefinesByType")

    for rel in rels:
        
        parent = rel.RelatingType
        if parent.is_a('IfcFurnitureType'):
            continue
        parent_name = parent.Name or parent.is_a()
      
        key = re.sub(r'[^a-z0-9]+', '', parent_name.lower())
        
        if parent.GlobalId not in nodes:
            nodes[parent.GlobalId]={
                "guid": parent.GlobalId,
                "ifc_id": parent.id(),
                "name": parent_name,
                "label": parent.is_a(),
                "type":parent.is_a()}
        
        for element in rel.RelatedObjects:
            
            if element.GlobalId in nodes:
                
                edges.append({
                    "from": element.GlobalId,
                    "to":parent.GlobalId,
                    "label": "HAS_TYPE",
                    "rel_guid": rel.GlobalId,
                    "rel_ifc_id": rel.id(),
                    "rel_type": rel.is_a()})
        
       
        for pset in parent.HasPropertySets:
             
            pset_name = pset.Name or pset.is_a()
                
            key = re.sub(r'[^a-z0-9]+', '', pset_name.lower())
            
            if pset.GlobalId not in nodes:
                
                nodes[pset.GlobalId]={
                    "guid": pset.GlobalId,
                    "ifc_id": pset.id(),
                    "name": pset_name,
                    "label": pset.is_a(),
                    "type": pset.is_a(),
                    "properties": {} }
            
            edges.append({
                "from": parent.GlobalId,
                "to": pset.GlobalId,
                "label": "HAS_PROPERTYSETS" }) 
                
            if hasattr(pset,"HasProperties") and pset.HasProperties:
                props = pset.HasProperties
                
                for i,prop in enumerate(props):
                    prop_name = prop.Name or f"prop_{i}"
                    prop_id = f"{pset.GlobalId}_{prop_name}_{i}"

                    if prop.is_a("IfcPropertySingleValue")  :
                        val = None
                        value_type = None
                        
                        if prop.NominalValue is not None:
                            value_type = prop.NominalValue.is_a()
                            
                            if  hasattr(prop.NominalValue,"wrappedValue"): 
                                val = prop.NominalValue.wrappedValue
                            else:
                                val = prop.NominalValue                               

                        unit = prop.Unit.Name if hasattr(prop,"unit") and prop.Unit else "" 
                        key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())

                        if val:
                            nodes[pset.GlobalId]["properties"][prop_name]= f"{val} {unit}".strip()
                              
                             
                    elif prop.is_a("IfcPropertyListValue"):
                        prop_list = prop.ListValues
                        vals=[]
                        value_type = None
                        
                        if prop_list:
                            for p in prop_list:
                                if value_type is None:
                                    value_type = p.is_a()
                                    
                                if hasattr(p,"wrappedValue"):
                                    vals.append(str(p.wrappedValue))
                                else:
                                    vals.append(str(p))
                        else:
                            vals=None
                            value_type = None
                        
                        
                        key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
                        unit = prop.Unit.Name if hasattr(prop,"Unit") and prop.Unit else ""

                        if vals:
                            joined_vals = ",".join(vals)
                            nodes[pset.GlobalId]["properties"][prop_name]= f"{joined_vals} {unit}".strip()
                                
                                   
                    elif prop.is_a("IfcPropertyEnumeratedValue"):
                        prop_enu = prop.EnumerationValues
                        vals =[]
                        value_type = None
                        
                        if prop_enu :
                            for p in prop_enu:
                                
                                if value_type is None:
                                    value_type = p.is_a()
                                    
                                if hasattr(p,"wrappedValue"):
                                    vals.append(str(p.wrappedValue))
                                else:
                                    vals.append(str(p))
                        else:
                            vals=None
                            value_type = None
 
                        key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
                        unit = prop.Unit.Name if hasattr(prop,"Unit") and prop.Unit else ""

                        if vals:
                            joined_vals = ",".join(vals)   
                            nodes[pset.GlobalId]["properties"][prop_name]= f"{joined_vals} {unit}".strip()
                                
                            
                    elif prop.is_a("IfcPropertyBoundedValue"):
                        value_type = None
                        lo = None
                        up = None
                        
                        if prop.LowerBoundValue is not None:
                            value_type = prop.LowerBoundValue.is_a()
                            if hasattr(prop.LowerBoundValue,"wrappedValue"):
                                lo = prop.LowerBoundValue.wrappedValue
                                if isinstance(lo,(int,float)):
                                    lo = str(float(lo))
                            else:
                                lo = str(prop.LowerBoundValue)          
                        
                        if prop.UpperBoundValue is not None:
                            if value_type is None:
                                value_type = prop.UpperBoundValue.is_a()
                            if hasattr(prop.UpperBoundValue,"wrappedValue"):
                                up = prop.UpperBoundValue.wrappedValue
                                if isinstance(up,(int,float)):
                                    up = str(float(up))
                            else:
                                up = str(prop.UpperBoundValue)
    
                              
                        key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
                        unit = prop.Unit.Name if hasattr(prop,"Unit") and prop.Unit else ""

                        if lo and up:     
                            nodes[pset.GlobalId]["properties"][prop_name]= f"{lo}{unit}<{up}{unit}"
                               
                                   
                    elif prop.is_a("IfcComplexProperty"):
                        prop_complex = prop.HasProperties
                        
                        key = re.sub(r'[^a-z0-9]+', '', prop_name.lower())
        
                        for i,sub in enumerate(prop_complex):
                            sub_name = f"{prop_name}_{sub.Name}" or f"sub_{i}"
                            sub_id = f"{prop_id}_{sub_name}_{i}"
                            
                            if sub.is_a("IfcPropertySingleValue"):
                                sval = None
                                value_type = None
                                
                                if sub.NominalValue is not None:
                                    value_type = sub.NominalValue.is_a()
                                    
                                    if hasattr(sub.NominalValue,"wrappedValue"):
                                        sval = sub.NominalValue.wrappedValue
                                    else:
                                        sval = str(sub.NominalValue)
                                else:
                                    sval = None
                                    value_type = None


                                key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""
                                
                                nodes[pset.GlobalId]["properties"]["sub_names"] = f"{sval} {unit}".strip()
                                     

                            elif sub.is_a("IfcPropertyListValue"):
                                sub_list = sub.ListValues
                                vals=[]
                                value_type = None
                                
                                if sub_list:
                                    for s in sub_list:
                                        if value_type is None:
                                            value_type = s.is_a()
                                        
                                        if hasattr(s, "wrappedValue"):
                                            vals.append(str(s.wrappedValue))
                                        else:
                                            vals.append(str(s))
                                else:
                                    vals = None
                                    value_type = None
                                

                                key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""

                                if vals:
                                    joined_vals = ",".join(vals)
                                    nodes[pset.GlobalId]["properties"]["sub_names"]= f"{joined_vals} {unit}".strip()
                                       
                                                
                            elif sub.is_a("IfcPropertyEnumeratedValue"):
                                sub_enu = sub.EnumerationValues
                                vals=[]
                                value_type = None
                                
                                if sub_enu :
                                    for s in sub_enu:
                                        if value_type is None:
                                            value_type = s.is_a()
                                        
                                        if hasattr(s,"wrappedValue"):
                                            vals.append(str(s.wrappedValue))
                                        else:
                                            vals.append(str(s))
                                else:
                                    vals = None
                                    value_type = None
                                

                                key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""

                                if vals:
                                    nodes[pset.GlobalId]["properties"]["sub_names"]= f"{joined_vals} {unit}".strip() 
                            
                            elif sub.is_a("IfcPropertyBoundedValue"):
                                value_type = None
                                
                                if sub.LowerBoundValue is not None:
                                    value_type = sub.LowerBoundValue.is_a()
                                    
                                    if hasattr(sub.LowerBoundValue,"wrappedValue"):
                                        lo = sub.LowerBoundValue.wrappedValue
                                        if isinstance(lo , (int,float)):
                                            lo = float(lo)
                                    else:
                                        lo = sub.LowerBoundValue
                                else:
                                    lo = None
                                    value_type = None
                                
                                if sub.UpperBoundValue is not None:
                                    if value_type is None:
                                        value_type = sub.UpperBoundValue.is_a()
                                    else:
                                        value_type = None
                                        
                                    if hasattr(sub.UpperBoundValue,"wrappedValue"):
                                        up = sub.UpperBoundValue.wrappedValue
                                        if isinstance(up , (int,float)):
                                            up = float(up)
                                    else:
                                        up = sub.UpperBoundValue
                                else:
                                    up = None
                                    value_type = None

                                key = re.sub(r'[^a-z0-9]+', '', sub_name.lower())
                                unit = sub.Unit.Name if hasattr(sub,"Unit") and sub.Unit else ""

                                if lo and up:
                                    nodes[pset.GlobalId]["properties"]["sub_names"] = f"{lo}{unit}<{up}{unit}"
                                        
                            
            elif pset.is_a("IfcPreDefinedPropertySet"):
                nodes[pset.GlobalId].pop("properties",None)
                el_info = pset.get_info()
                ignored_keys = ["id","GlobalId","Name","Description","Type","OwnerHistory"]
                
                for key,value in el_info.items():
                    if key in ignored_keys or value in [ None,[],{},""]:
                        continue
                    nodes[pset.GlobalId][key] = value
               
    
            elif hasattr(pset,"Quantities") and pset.Quantities:
                qtys = pset.Quantities
            
                for i, qty in enumerate(qtys):
                    qty_name = qty.Name or f"qty_{i}"
                    qty_id = f"{pset.GlobalId}_{qty_name}_{i}"
                    val = None
                    value_type = None
                    unit_str = None
                    
                    if qty.is_a("IfcQuantityLength"):
                        if hasattr(qty,"LengthValue") and qty.LengthValue is not None:
                            val = float(qty.LengthValue) * unit_scale
                            unit_str = "m"
                            
                    if qty.is_a("IfcQuantityArea"):
                        if hasattr(qty,"AreaValue") and qty.AreaValue is not None:
                            val = float(qty.AreaValue) 
                            unit_str = "m^2"
                            
                    if qty.is_a("IfcQuantityVolume"):
                        if hasattr(qty,"VolumeValue") and qty.VolumeValue is not None :
                            val = float(qty.VolumeValue) 
                            unit_str = "m^3"
                            
                    if qty.is_a("IfcQuantityWeight"):
                        if hasattr(qty,"WeightValue") and qty.WeightValue is not None:
                            val = float(qty.WeightValue)
                            unit_str = qty.Unit.Name if hasattr(qty,"Unit") and qty.Unit else None
                    
                    if qty.is_a("IfcQuantityCount"):
                        if hasattr(qty,"CountValue") and qty.CountValue is not None:
                            val = float(qty.CountValue)
                            unit_str = qty.Unit.Name if hasattr(qty,"Unit") and qty.Unit else None
                            
                    if qty.is_a("IfcQuantityTime"):
                        if hasattr(qty,"TimeValue") and qty.TimeValue is not None:
                            val = float(qty.TimeValue)
                            unit_str = qty.Unit.Name if hasattr(qty,"Unit") and qty.Unit else None
            
                    qty_type = qty.is_a()
                    if qty_type == "IfcQuantityWeight":
                        value_type = "IfcMassMeasure"
                    else:
                        qty_type = qty_type.replace("IfcQuantity", "Ifc")
                        value_type = f"{qty_type}" + "Measure"
            
                    
                    key = re.sub(r'[^a-z0-9]+', '', qty_name.lower())
                    
                    nodes[pset.GlobalId]["properties"][qty_name] = f"{val}{unit_str}"
            
       
#==========================================================================================================
    rels = ifc_file.by_type("IfcRelAssociatesMaterial")
    
    for rel in rels:
        material = rel.RelatingMaterial
        if not material:
            continue
            
        for element in rel.RelatedObjects:
            
            if element.GlobalId in nodes:
               
                if material.is_a("IfcMaterial"):
                    mat_name = material.Name or material.is_a()
                    mat_id = f"MAT_{material.is_a()}_{mat_name}"
                    key = re.sub(r'[^a-z0-9]+', '', mat_name.lower())
                    
                    if mat_id not in nodes:
                        nodes[mat_id]={
                            "guid": mat_id,
                            "ifc_id": material.id(),
                            "name": mat_name,
                            "label": "Material",
                            "type": material.is_a()}
                    
                    edges.append({
                        "from": element.GlobalId,
                        "to": mat_id,
                        "label": "HAS_MATERIAL",
                        "rel_guid": rel.GlobalId,
                        "rel_ifc_id": rel.id(),
                        "rel_type": rel.is_a()})
                            
                elif material.is_a("IfcMaterialLayerSetUsage"):
                    material_info = material.get_info()
                    
                    usage_offset = material_info.get("OffsetFromReferenceLine", None)
                    if usage_offset is not None:
                        usage_offset *= unit_scale
                        
                    layer_set_direction = material_info.get("LayerSetDirection", None)
                    direction_sense = material_info.get("DirectionSense", None)
                    
                    layer_set = material.ForLayerSet
                    if layer_set:
                        layer_set_info = layer_set.get_info()
                        layer_set_name = layer_set_info.get("LayerSetName", None)
                        
                        if hasattr(layer_set, 'MaterialLayers') and layer_set.MaterialLayers:
                            layers = layer_set.MaterialLayers
                            
                            for i, layer in enumerate(layers):
                                if layer.Material:
                                    mat = layer.Material
                                    mat_name = mat.Name or mat.is_a()
                                    mat_id = f"MAT_{mat.is_a()}_{mat_name}"
                                    key = re.sub(r'[^a-z0-9]+', '', mat_name.lower())
                                
                                    if mat_id not in nodes:
                                        nodes[mat_id]={
                                            "guid": mat_id,
                                            "ifc_id": mat.id(),
                                            "name": mat_name,
                                            "label": "Material",
                                            "type": mat.is_a() }
                                    
                                    layer_info = layer.get_info()
                                    
                                    layer_thickness = layer_info.get("LayerThickness", 0.0) * unit_scale
                                    
                                    edges.append({
                                        "from": element.GlobalId,
                                        "to": mat_id,
                                        "label": "HAS_MATERIAL",
                                        "rel_guid": rel.GlobalId,
                                        "rel_ifc_id": rel.id(),
                                        "rel_type": rel.is_a(),
                                        "properties":{
                                            "layer_index": i,                           
                                            "layer_thickness": layer_thickness, 
                                            "layer_name": layer_info.get("Name", ""),   
                                            "is_ventilated": layer_info.get("IsVentilated", None),
                                            "layer_set_name": layer_set_name,
                                            "usage_offset": usage_offset,
                                            "layer_set_direction": layer_set_direction,
                                            "direction_sense": direction_sense,
                                            "layer_id": layer.id(),
                                            "layer_set_id": layer_set.id(),
                                            "material_id": material.id() }})
                                   
                elif material.is_a("IfcMaterialLayerSet"):
                    layer_set = material
                    layer_set_info = layer_set.get_info()
                    layer_set_name = layer_set_info.get("LayerSetName", None)
    
                    if hasattr(layer_set, 'MaterialLayers') and layer_set.MaterialLayers:
                        layers = layer_set.MaterialLayers
    
                        for i, layer in enumerate(layers):
                            if layer.Material:
                                mat = layer.Material
                                mat_name = mat.Name or mat.is_a()
                                mat_id = f"MAT_{mat.is_a()}_{mat_name}"
                                key = re.sub(r'[^a-z0-9]+', '', mat_name.lower()) 
    
                                if mat_id not in nodes:
                                    nodes[mat_id]={
                                        "guid": mat_id,
                                        "ifc_id": mat.id(),
                                        "name": mat_name,
                                        "label": "Material",
                                        "type": mat.is_a() }
                                     
                                layer_info = layer.get_info()
                                
                                layer_thickness = layer_info.get("LayerThickness", 0.0) * unit_scale
    
                                edges.append({
                                    "from": element.GlobalId,
                                    "to": mat_id, 
                                    "label": "HAS_MATERIAL",
                                    "rel_guid": rel.GlobalId,
                                    "rel_ifc_id": rel.id(),
                                    "rel_type": rel.is_a(),
                                    "properties": {
                                        "layer_index": i,                           
                                        "layer_thickness": layer_thickness, 
                                        "layer_name": layer_info.get("Name", ""),   
                                        "is_ventilated": layer_info.get("IsVentilated", None),
                                        "layer_set_name": layer_set_name,
                                        "layer_id": layer.id(),
                                        "layer_set_id": material.id() }})
                                
                elif material.is_a("IfcMaterialList"):
                    if hasattr(material, 'Materials') and material.Materials:
                        for i, mat in enumerate(material.Materials):
                            mat_name = mat.Name or mat.is_a()
                            mat_id = f"MAT_{mat.is_a()}_{mat_name}"
                            key = re.sub(r'[^a-z0-9]+', '', mat_name.lower())
                            
                            if mat_id not in nodes:
                                nodes[mat_id] = {
                                    "guid": mat_id,
                                    "ifc_id": mat.id(),
                                    "name": mat_name,
                                    "label": "Material",
                                    "type": mat.is_a()}
                        
                            edges.append({
                                "from": element.GlobalId,
                                "to": mat_id,
                                "label": "HAS_MATERIAL",
                                "rel_guid": rel.GlobalId,
                                "rel_ifc_id": rel.id(),
                                "rel_type": rel.is_a(),
                                "properties": {
                                    "list_index": i,
                                    "list_id": material.id() }})
                
                elif material.is_a("IfcMaterialConstituentSet"):
                    if hasattr(material, 'MaterialConstituents') and material.MaterialConstituents:
                        for constituent in material.MaterialConstituents:
                            if constituent.Material:
                                mat = constituent.Material
                                mat_name = mat.Name or mat.is_a()
                                mat_id = f"MAT_{mat.is_a()}_{mat_name}"
                                key = re.sub(r'[^a-z0-9]+', '', mat_name.lower())
    
                                if mat_id not in nodes:
                                    nodes[mat_id] = {
                                        "guid": mat_id,
                                        "ifc_id": mat.id(),
                                        "name": mat_name,
                                        "label": "Material",
                                        "type": mat.is_a()}
        
                                constituent_info = constituent.get_info()
        
                                edges.append({
                                    "from": element.GlobalId,
                                    "to": mat_id,
                                    "label": "HAS_MATERIAL",
                                    "rel_guid": rel.GlobalId,
                                    "rel_ifc_id": rel.id(),
                                    "rel_type": rel.is_a(),
                                    "properties": {
                                        "constituent_name": constituent_info.get("Name", None),
                                        "constituent_fraction": constituent_info.get("Fraction", None),
                                        "constituent_category": constituent_info.get("Category", None),
                                        "constituent_description": constituent_info.get("Description", None),
                                        "constituent_id": constituent.id(), 
                                        "constituent_set_id": material.id() }})
                                            
                elif material.is_a("IfcMaterialProfileSetUsage"):
                    material_info = material.get_info()
                    
                    reference_extent = material_info.get("ReferenceExtent", None)
                    if reference_extent is not None:
                        reference_extent *= unit_scale
                        
                    offset_values = material_info.get("OffsetValues", None)
                    if offset_values:
                        
                        offset_values = [val * unit_scale for val in list(offset_values)]
                        
                    profile_set = material.ForProfileSet
                    
                    if profile_set:
                        profile_set_info = profile_set.get_info() 
                        profile_set_name = profile_set_info.get("Name", None) 
                        
                        if hasattr(profile_set, 'MaterialProfiles') and profile_set.MaterialProfiles:
                            profiles = profile_set.MaterialProfiles 
                            
                            for i, profile in enumerate(profiles):
                                if profile.Material:
                                    mat = profile.Material
                                    mat_name = mat.Name or mat.is_a()
                                    mat_id = f"MAT_{mat.is_a()}_{mat_name}"
                                    key = re.sub(r'[^a-z0-9]+', '', mat_name.lower())
    
                                    if mat_id not in nodes:
                                        nodes[mat_id]={
                                            "guid": mat_id,
                                            "ifc_id": mat.id(),
                                            "name": mat_name,
                                            "label": "Material",
                                            "type": mat.is_a()}
                                    
                                    profile_info = profile.get_info() 
                                    
                                    profile_def = profile.Profile
                                    profile_def_name = profile_def.Name if profile_def else None
                                    profile_def_type = profile_def.is_a() if profile_def else None 
                                    
                                    edges.append({
                                        "from": element.GlobalId,
                                        "to": mat_id,
                                        "label": "HAS_MATERIAL",
                                        "rel_guid": rel.GlobalId,
                                        "rel_ifc_id": rel.id(),
                                        "rel_type": rel.is_a(),
                                        "properties": {
                                                "profile_index": i,                           
                                                "profile_name": profile_info.get("Name", None),   
                                                "priority": profile_info.get("Priority", None),
                                                "profile_set_name": profile_set_name,
                                                "profile_def_name" : profile_def_name,
                                                "profile_def_type" : profile_def_type,
                                                "reference_extent": reference_extent,
                                                "offset_values": offset_values,
                                                "profile_def_id": profile_def.id() if profile_def else None,
                                                "profile_id": profile.id(),
                                                "profile_set_id": profile_set.id(),
                                                "material_id": material.id() }})
                                
                elif material.is_a("IfcMaterialProfileSet"):
                    profile_set_info = material.get_info()
                    profile_set_name = profile_set_info.get("Name", None)
    
                    if hasattr(material, 'MaterialProfiles') and material.MaterialProfiles:
                        profiles = material.MaterialProfiles
    
                        for i, profile in enumerate(profiles):
                            if profile.Material:
                                mat = profile.Material
                                mat_name = mat.Name or mat.is_a()
                                mat_id = f"MAT_{mat.is_a()}_{mat_name}"
                                key = re.sub(r'[^a-z0-9]+', '', mat_name.lower())
    
                                if mat_id not in nodes:
                                    nodes[mat_id]={
                                        "guid": mat_id,
                                        "ifc_id": mat.id(),
                                        "name": mat_name,
                                        "label": "Material",
                                        "type": mat.is_a()}
    
                                profile_info = profile.get_info() 
                                
                                profile_def = profile.Profile
                                profile_def_name = profile_def.Name if profile_def else None
                                profile_def_type = profile_def.is_a() if profile_def else None
    
                                edges.append({
                                    "from": element.GlobalId,
                                    "to": mat_id,
                                    "label": "HAS_MATERIAL",
                                    "rel_guid": rel.GlobalId,
                                    "rel_ifc_id": rel.id(),
                                    "rel_type": rel.is_a(),
                                    "properties": {
                                        "profile_index": i,                           
                                        "profile_name": profile_info.get("Name", None),   
                                        "priority": profile_info.get("Priority", None),
                                        "profile_set_name": profile_set_name,
                                        "profile_def_name" : profile_def_name,
                                        "profile_def_type" : profile_def_type,
                                        "profile_def_id": profile_def.id() if profile_def else None,
                                        "profile_id": profile.id(),
                                        "profile_set_id": material.id() }})

 
   
    for node in nodes.values():
        if node.get("name") in ["other","Other"]:
            node["name"] = node.get("type")
        
        if node.get("key") in ["other","Other"]:
            node["key"] = node.get("type")
            
        if "description" in node:
            if node["description"] is None or node["description"] == "None" or node["description"] in [ [],"",{}]:
                node.pop("description")
        
        if "properties" in node and "description" in node["properties"]:
            if node["properties"]["description"] in [None, "None", "", [], {}]:
                node["properties"].pop("description")


    return nodes,edges

nodes,edges = extract_spatialhierarchy(ifc_file)

