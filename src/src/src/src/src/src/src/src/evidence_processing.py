    # ==========================================================
    # 6. Assembly & Execution
    # ==========================================================
    
    if topology_val not in ["BOTTLENECK", "CENTRALITY"]:
        
        cypher_query = "\n".join(match_clauses)
        
        if where_clauses:
            cypher_query += "\nWHERE " + " AND ".join(where_clauses)
            
        if optional_matches:
            cypher_query += "\n" + "\n".join(optional_matches)
        
        cypher_query += "\nRETURN DISTINCT " + ",\n\t".join(returns)

  
    try:
        with driver.session() as session:
            result = session.run(cypher_query, **params)
            records = [record.data() for record in result]
            
            if not records:
                return "No elements or spaces found matching all the requested criteria."

            unique_records = {}
            for r in records:
                unique_key = f"{r.get('TargetName', 'unk')}_{r.get('SpaceName', 'unk')}_{r.get('StoreyName', 'unk')}"
                if unique_key not in unique_records:
                    unique_records[unique_key] = r
                    if 'FilteredProperties' not in unique_records[unique_key]:
                        unique_records[unique_key]['FilteredProperties'] = []
                else:
                    existing_props = unique_records[unique_key].get('FilteredProperties', [])
                    new_props = r.get('FilteredProperties', [])
                    if isinstance(existing_props, list) and isinstance(new_props, list):
                        unique_records[unique_key]['FilteredProperties'] = list(set(existing_props + new_props))

            final_records = list(unique_records.values())

            # ==========================================================
            # (Integrated Property Filtering)
            # ==========================================================
            if props:
                parsed_conditions = []
                if condition:
                    tokens = re.findall(r"([<>=!]+)\s*([\d.]+)|(and|or)", condition.lower())
                    ops = {
                        '>': operator.gt, '<': operator.lt, 
                        '>=': operator.ge, '<=': operator.le, 
                        '=': operator.eq, '==': operator.eq
                    }
                    current_logic = "and"
                    for gt_lt, val_str, logic in tokens:
                        if logic:
                            current_logic = logic
                        elif gt_lt and val_str:
                            comp_func = ops.get(gt_lt)
                            target_val = float(val_str)
                            if comp_func:
                                parsed_conditions.append((comp_func, target_val, current_logic))
            
                filtered_records = []
                
                for record in final_records:
                    props_list = record.get('FilteredProperties', [])
                    if isinstance(props_list, dict):
                        props_list = [f"{k}: {v}" for k, v in props_list.items()]
                    
                    parsed_parts = []
                    for p in props_list:
                        p_str = str(p)
                        parts = [part.strip() for part in p_str.split(',')]
                        for part in parts:
                            if ":" in part:
                                k, v = part.split(":", 1)
                                parsed_parts.append((k.strip(), v.strip(), part))
                            else:
                                parsed_parts.append((part, "Available", part))
                    
                    clean_properties = []
                    keep_record = True if not parsed_conditions else False
                    
                    for prop_name in props:
                        p_low = prop_name.lower()
                        has_exact_match = any(item[0].lower() == p_low for item in parsed_parts)
                        
                        for k, v, original_part in parsed_parts:
                            k_low = k.lower()
                            is_valid_target = False
                            
                            if has_exact_match:
                                if k_low == p_low:
                                    is_valid_target = True
                            else:
                                if p_low in k_low:
                                    exclusions = ['sill', 'head', 'default', 'offset', 'frame', 'lining', 'trim']
                                    if not any(ex in k_low for ex in exclusions) or any(ex in p_low for ex in exclusions):
                                        is_valid_target = True
                                        
                            if is_valid_target:
                                if parsed_conditions:
                                    num_match = re.search(r"([\d.]+)", v)
                                    if num_match:
                                        prop_val = float(num_match.group(1))
                                        is_match = True
                                        for comp_func, target_val, logic in parsed_conditions:
                                            res = comp_func(prop_val, target_val)
                                            if logic == "or":
                                                is_match = is_match or res
                                            else:
                                                is_match = is_match and res
                                        
                                        if is_match:
                                            keep_record = True
                                            if original_part not in clean_properties:
                                                clean_properties.append(original_part)
                                else:
                                    if original_part not in clean_properties:
                                        clean_properties.append(original_part)
                    
                    if keep_record and clean_properties:
                        record['FilteredProperties'] = clean_properties
                        filtered_records.append(record)
                        
                final_records = filtered_records
            
            # ==========================================================
            # (Material Thickness)
            # ==========================================================
            if condition and raw_mat_filter and not props:
                if 'parsed_conditions' not in locals() or not parsed_conditions:
                    tokens = re.findall(r"([<>=!]+)\s*([\d.]+)|(and|or)", condition.lower())
                    ops = {
                        '>': operator.gt, '<': operator.lt, 
                        '>=': operator.ge, '<=': operator.le, 
                        '=': operator.eq, '==': operator.eq
                    }
                    parsed_conditions = []
                    current_logic = "and"
                    for gt_lt, val_str, logic in tokens:
                        if logic:
                            current_logic = logic
                        elif gt_lt and val_str:
                            comp_func = ops.get(gt_lt)
                            target_val = float(val_str)
                            if comp_func:
                                parsed_conditions.append((comp_func, target_val, current_logic))
            
                if parsed_conditions:
                    filtered_mats_records = []
                    for record in final_records:
                        mat_list = record.get('MaterialData', [])
                        if not isinstance(mat_list, list):
                            mat_list = []
                            
                        keep_record = False
                        for m in mat_list:
                            raw_layer = m.get('RawLayerData', '')
                            thick_match = re.search(r'layer_thickness:\s*([0-9.]+)', str(raw_layer))
                            if thick_match:
                                thick_val = float(thick_match.group(1))
                                
                                is_match = True
                                for comp_func, target_val, logic in parsed_conditions:
                                    res = comp_func(thick_val, target_val)
                                    if logic == "or":
                                        is_match = is_match or res
                                    else: # and
                                        is_match = is_match and res
                                        
                                if is_match:
                                    keep_record = True
                                    break 
                                    
                        if keep_record:
                            filtered_mats_records.append(record)
                            
                    final_records = filtered_mats_records

            
            optimized_records = optimize_bim_results_for_llm(final_records, props)
            return json.dumps(optimized_records, ensure_ascii=False)

    except Exception as e:
        print(f"An error occurred: {e}")
        return json.dumps([])
#=======================================================================================================

def optimize_bim_results_for_llm(raw_results, props=None):

    # ==========================================================
    # 1. Spatial Context Normalization
    # ==========================================================
    
    grouped_results = {}
    space_id_mapping = {} 
    space_name_counters = {}
    
    for item in raw_results:
        target_name = item.get("TargetName", "Unknown")
        base_target_name = target_name.rsplit(":", 1)[0] if ":" in target_name else target_name
        target_type = item.get("TargetType", "Unknown")
        
        is_space_target = target_type == "IfcSpace" or "space" in target_name.lower()
        
        if is_space_target:
            readable_space_name = base_target_name
        else:
            space_name = item.get("SpaceName", "N/A")
            space_id = item.get("SpaceID") or item.get("SpaceGUID") or item.get("SpaceElementId") or "Shared_ID"
            
            if space_id not in space_id_mapping:
                space_id_mapping[space_id] = space_name
                
            readable_space_name = space_id_mapping[space_id]
    
        storey_name = item.get("StoreyName", "Unknown_Level")
        
        clean_materials = []
        if item.get("MaterialData"):
            for mat in item["MaterialData"]:
                raw_layer = mat.get("RawLayerData", "")
                thickness_match = re.search(r'layer_thickness:\s*([0-9.]+)', raw_layer)
                thickness = f"{thickness_match.group(1)} m" if thickness_match else "Unknown"
                
                clean_materials.append({
                    "Material": mat.get("Material", "Unknown"),
                    "Thickness": thickness
                })
        
        
        # ==========================================================
        # 2. Material and Property Evidence Extraction
        # ==========================================================
        
        properties_data = {}
        target_details = item.get("TargetDetails", "")
        
        if isinstance(target_details, str) and target_details:
            dim_match = re.search(r'intrinsic_dimensions\s*:\s*(\{.*?\})', target_details)
            if dim_match:
                try:
                    dims_str = dim_match.group(1).replace("'", '"')
                    properties_data.update(json.loads(dims_str))
                except json.JSONDecodeError:
                    properties_data["Dimensions"] = dim_match.group(1)
                    
        props_source = item.get("FilteredProperties") or item.get("Properties")
        if props_source:
            if isinstance(props_source, dict):
                properties_data.update(props_source)
            elif isinstance(props_source, list):
                for p in props_source:
                    if ":" in p:
                        k, v = p.split(":", 1)
                        properties_data[k.strip()] = v.strip()
                    else:
                        properties_data[p] = "Available"
        
        for key, value in properties_data.items():
            if isinstance(value, float):
                properties_data[key] = round(value, 4)
            elif isinstance(value, str):
                try:
                    properties_data[key] = round(float(value), 4)
                except ValueError:
                    pass

        # ==========================================================
        # 3. Query-Specific Property Filtering
        #    Exact-Match with Lexical Fallback
        # ==========================================================
        if props:
            filtered_properties = {}
            for prop_name in props:
                p_low = prop_name.lower()
                
                has_exact_match = any(k.lower() == p_low for k in properties_data.keys())
                
                for k, v in properties_data.items():
                    k_low = k.lower()
                    if has_exact_match:
                        if k_low == p_low:
                            filtered_properties[k] = v
                    else:
                        if p_low in k_low:
                            exclusions = ['sill', 'head', 'default', 'offset']
                            if any(ex in k_low for ex in exclusions) and not any(ex in p_low for ex in exclusions):
                                continue
                            filtered_properties[k] = v
            properties_data = filtered_properties

        
        # ==========================================================
        # 4. Topology Evidence Extraction and Path Representation
        # ==========================================================
        
        topology_data = {}
    
        if "Score" in item:
            try:
                topology_data["Centrality_Score"] = round(float(item["Score"]), 4)
            except (ValueError, TypeError):
                topology_data["Centrality_Score"] = item["Score"]
                
        if "ReferenceSpace" in item:
            topology_data["Connected_To"] = item["ReferenceSpace"]
        
        if "ConnectionType" in item:
            topology_data["Connection_Type"] = item["ConnectionType"]
                  
        route_data = item.get("Route", [])
        avg_door_val = item.get("AvgDoorCrossing") or item.get("DoorsToCross") or 0
        total_steps_val = item.get("TotalSteps") or 0
        
        if route_data:
            if route_data == ['Global Analysis'] or route_data == 'Global Analysis':
                topology_data["Readable_Path"] = f'"Global Analysis" -> (Mean Topological Depth: {total_steps_val} steps | Average Doors to Cross: {avg_door_val})'
            
            else:
                conn_types = item.get("ConnectionTypes", [])
                
                path_string = ""
                for i in range(len(route_data)):
                    path_string += f'"{route_data[i]}"'
                    if i < len(route_data) - 1:
                        c_type = conn_types[i] if i < len(conn_types) else "UNKNOWN"
                        path_string += f" -> [{c_type}] -> "
                
                path_string += f" (Total Depth: {total_steps_val} steps | Doors to cross: {avg_door_val})"
                topology_data["Readable_Path"] = path_string

        if "BottleneckNeighbors" in item and item["BottleneckNeighbors"]:
            neighbor_relations = []
            door_connections = 0
            open_connections = 0
            
            for n in item["BottleneckNeighbors"]:
                if n.get("neighbor") and n.get("relation"):
                    clean_neighbor = n["neighbor"].rsplit(":", 1)[0] if ":" in n["neighbor"] else n["neighbor"]
                    impact = n.get("impact", "Unknown Impact")
                    relation_str = f"{base_target_name} -> [{n['relation']}] -> {clean_neighbor} | Status: {impact}"
                    neighbor_relations.append(relation_str)
                    
                    if n['relation'] == 'ACCESS_BY_DOOR':
                        door_connections += 1
                    elif n['relation'] == 'OPEN_ACCESS':
                        open_connections += 1
            
            if neighbor_relations:
                topology_data["Critical_Spatial_Anchors"] = neighbor_relations
                topology_data["Bottleneck_Profile"] = f"Doors: {door_connections}, Openings: {open_connections}"


        # ==========================================================
        # 5. Evidence Fingerprinting and Entity Consolidation
        # ==========================================================
        
        mat_fingerprint = json.dumps(clean_materials, sort_keys=True)
        prop_fingerprint = json.dumps(properties_data, sort_keys=True)
        top_fingerprint = json.dumps(topology_data, sort_keys=True) 
        
        if is_space_target:
            technical_fingerprint = f"Space_{base_target_name}_{prop_fingerprint}"
        else:
            technical_fingerprint = f"Element_{base_target_name}_{storey_name}_{mat_fingerprint}_{prop_fingerprint}_{top_fingerprint}"
            
        if technical_fingerprint not in grouped_results:
            new_entry = {
                "Element_Name": base_target_name,
                "Type": target_type,
                "Storey": storey_name,
                "Related_Spaces": [readable_space_name],
            }
            if clean_materials:
                new_entry["Materials"] = clean_materials
            if properties_data:
                new_entry["Properties"] = properties_data
                    
            new_entry.update(topology_data)
            grouped_results[technical_fingerprint] = new_entry
        else:
            if readable_space_name not in grouped_results[technical_fingerprint]["Related_Spaces"]:
                grouped_results[technical_fingerprint]["Related_Spaces"].append(readable_space_name)
            
    # ==========================================================
    # 6. Final Context Cleanup and Output Normalization
    # ==========================================================
    
    cleaned_final_results = []
    for entry in grouped_results.values():
        related_spaces = entry.get("Related_Spaces", [])
        element_name = entry.get("Element_Name")
        
        if len(related_spaces) == 1 and related_spaces[0] == element_name:
            del entry["Related_Spaces"]
            
        elif len(related_spaces) > 1 and element_name in related_spaces:
            entry["Related_Spaces"] = [s for s in related_spaces if s != element_name]
            
        cleaned_final_results.append(entry)
            
    return cleaned_final_results
