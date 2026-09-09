import chromadb
from chromadb.utils import embedding_functions

ifc_schema =[
  {
    "ifc_class": "IfcProject",
    "description": "The root and highest level of the spatial structure hierarchy representing the entire project or facility.",
    "synonyms": ["project", "entire project", "whole project", "facility", "development"]
  },
  {
    "ifc_class": "IfcSite",
    "description": "The geographical site, terrain, topography, or plot of land where the building or facility is located.",
    "synonyms": ["site", "plot", "terrain", "landscape", "topography", "land", "parcel", "ground"]
  },
  {
    "ifc_class": "IfcBuilding",
    "description": "The main building, structure, or edifice constructed on the site.",
    "synonyms": ["building", "structure", "edifice", "complex", "block", "facility"]
  },
  {
    "ifc_class": "IfcBuildingStorey",
    "description": "A specific elevation level, floor, or storey within a building.",
    "synonyms": ["storey", "story", "floor", "level", "ground floor", "first floor", "basement", "mezzanine", "tier"]
  },
  {
    "ifc_class": "IfcSpace",
    "description": "A 3D spatial volume representing internal spaces, rooms, halls, corridors, or functional areas for human occupancy or equipment.",
    "synonyms": ["space", "room", "corridor", "hall", "lobby", "area", "kitchen", "bedroom", "bathroom", "restroom", "toilet", "wc", "living room", "office", "balcony", "terrace"]
  },
  {
    "ifc_class": "IfcWall",
    "description": "Vertical constructions typically bounding or subdividing spaces, including non-standard, curved, or complex walls.",
    "synonyms": ["wall", "partition", "interior wall", "exterior wall", "shear wall", "retaining wall", "divider"]
  },
  {
    "ifc_class": "IfcWallStandardCase",
    "description": "Standard vertical walls with a constant thickness and uniform cross-section along their path.",
    "synonyms": ["wall", "standard wall", "basic wall", "straight wall", "uniform wall", "straight partition"]
  },
  {
    "ifc_class": "IfcCurtainWall",
    "description": "Exterior facade systems, typically non-load-bearing, comprising grids and infill panels like glass.",
    "synonyms": ["curtain wall", "glass wall", "glass facade", "storefront", "exterior glazing", "glazed facade", "facade system"]
  },
  {
    "ifc_class": "IfcSlab",
    "description": "A heavy, load-bearing planar structural component oriented horizontally. It forms the primary structural core of floors and roofs, transferring vertical dead and live loads to beams or columns. It represents the reinforced concrete deck or foundation mat.",
    "synonyms": ["structural slab","concrete slab","load-bearing floor","structural deck","floor slab","roof slab","foundation slab","mat foundation","structural concrete deck"]
  },
  {
    "ifc_class": "IfcRoof",
    "description": "The uppermost structural covering of a building providing protection from weather.",
    "synonyms": ["roof", "rooftop", "canopy", "pitched roof", "flat roof", "shelter", "overhang"]
  },
  {
    "ifc_class": "IfcDoor",
    "description": "Operable elements for access or egress through building components like walls.",
    "synonyms": ["door", "doorway", "portal", "revolving door", "sliding door"]
  },
  {
    "ifc_class": "IfcWindow",
    "description": "Glazed openings in a building envelope for light, ventilation, or views.",
    "synonyms": ["window", "skylight", "glazing", "casement", "pane", "louver", "glass window"]
  },
  {
    "ifc_class": "IfcCovering",
    "description": "A non-structural, architectural surface finish layer applied to spaces or building elements for aesthetic, protective, or acoustic purposes. It represents false ceilings, suspended ceilings, interior wall linings, claddings, skirtings, and finish floor coverings like carpets or tiles.",
    "synonyms": ["covering","architectural finish","suspended ceiling","false ceiling","ceiling tile","ceiling lining", "cladding","baseboard","skirting board","wall finish","finish flooring","carpet","plaster layer","paint finish"]
  },
  {
    "ifc_class": "IfcMember",
    "description": "A generic linear structural element, typically utilized as a constituent part within complex structural assemblies (e.g., trusses, space frames) or applied when specific classifications like IfcBeam or IfcColumn are not explicitly defined in the schema.",
    "synonyms": ["structural member", "framing element", "strut", "brace", "truss chord", "diagonal member", "generic linear element"]
  },
  {
    "ifc_class": "IfcPlate",
    "description": "Thick planar elements, typically flat plates, sheets, or panels often used in steel or timber construction.",
    "synonyms": ["plate", "sheet", "panel", "flat piece", "gusset", "web plate", "flange"]
  },

    {
    "ifc_class": "IfcBeam",
    "description": "A primary linear structural element, typically oriented horizontally or on an incline, specifically designed to carry transversal loads and withstand bending moments across a defined span.",
    "synonyms": ["beam", "girder", "joist", "lintel", "purlin", "horizontal framing", "spanner"]
  }
]

client = chromadb.PersistentClient(path=CHROMA_DB_PATH)


embed_model = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name= EMBEDDINGS_MODEL_PATH)

collection = client.get_or_create_collection(
    name="ifc_physical_elements",
    embedding_function=embed_model,
    metadata={"hnsw:space": "cosine"} )

documents = [] 
metadatas = [] 
ids = []

id_counter = 0

for item in ifc_schema:
    ifc_class = item["ifc_class"]
    description = item["description"]
    
    documents.append(f"Description: {description}")
    metadatas.append({"ifc_class": ifc_class})
    ids.append(f"desc_{id_counter}")
    id_counter += 1
    
    for synonym in item["synonyms"]:
        documents.append(synonym) 
        metadatas.append({"ifc_class": ifc_class})
        ids.append(f"syn_{id_counter}")
        id_counter += 1

collection.upsert(
    documents=documents,
    metadatas=metadatas,
    ids=ids)

# ==========================================
DISTANCE_THRESHOLD = 0.6

def map_concept_to_ifc_classes(concept_query: str) -> List[str]:
    
    """
    Translates a layman term (e.g., 'wall') to standard IFC classes (e.g., ['IfcWall']) using ChromaDB.
    """
    if not concept_query:
        return []

    results = collection.query(
        query_texts=[concept_query],
        n_results=3, 
        include=['metadatas', 'distances'] )

    extracted_ifc_classes = []
    
    if results['metadatas'] and results['distances']:
        for metadata_list, distance_list in zip(results['metadatas'], results['distances']):
            for meta, dist in zip(metadata_list, distance_list):
                if dist <= DISTANCE_THRESHOLD:
                    extracted_ifc_classes.append(meta['ifc_class'])

    return list(set(extracted_ifc_classes))
