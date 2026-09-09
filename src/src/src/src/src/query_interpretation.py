from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# تغییرات در کلاس TopologyRelation
class TopologyRelation(str, Enum):
    SHORTEST_PATH = "SHORTEST_PATH"        
    ADJACENT = "ADJACENT"                  
    DIRECT_ACCESS = "DIRECT_ACCESS"        
    DOOR_ACCESS = "DOOR_ACCESS"            
    ANY_ACCESS = "ANY_ACCESS"              
    NONE = "NONE"
    # ---> مقادیر جدید اضافه شده <---
    BOTTLENECK = "BOTTLENECK"            # نقاط بحرانی (Articulation Points)
    CENTRALITY = "CENTRALITY"            # شاهراه‌ها و مرکزیت (Betweenness)
    CRITICAL_ROUTE = "CRITICAL_ROUTE"    # فضای حیاتی در یک مسیر خاص

class BIMQuerySchema(BaseModel):
     
    element_type: str = Field(
        ..., 
        description=(
            "The general category, class, or architectural subtype of the element (e.g., wall, beam, slab, sliding door, space, room, building storey). "
            "Always extract the most specific architectural category mentioned. If the user uses phrases like 'called [Category]', extract the category here. "
            "NOTE: When a query asks about spaces containing, hosting, or bounded by physical elements (e.g., walls, windows, doors), set element_type to the target physical element being evaluated or filtered, NOT 'space'."
        )
    )
    
    target_element_name: Optional[str] = Field(
        None, 
        description="STRICTLY for unique alphanumeric identifiers, instance names, or specific tags (e.g., Wall-01, Door_A, GUID_123). DO NOT use this field for general architectural concepts or sub-categories. Only populate this if the user specifies an exact, unique instance ID."
    )
    
    reference_space_name: Optional[str] = Field(
        None, 
        description=(
            "CRITICAL: The primary focal space, subject of analysis, origin room, or functional zone. "
            "ALWAYS populate this field whenever a specific space/room name is mentioned in the query. "
            "This applies to:\n"
            "1. Single-Space Topological/Accessibility Analysis: The space whose structural role, shortest paths, connectivity, or metrics are being analyzed (e.g., 'role of the hallway', 'shortest path from living room').\n"
            "2. Spatial Context: The space in which another element resides (e.g., 'doors in kitchen').\n"
            "3. Origin Node: The starting space for pathfinding/routing queries.\n"
            "Examples: 'corridor', 'foyer', 'stair', 'living room', 'kitchen', 'bathroom', 'office', 'bedroom'."
        )
    )

    target_space_name: Optional[str] = Field(
        default=None,
        description=(
            "CRITICAL FOR MULTI-NODE QUERIES: The secondary or destination spatial entity. "
            "ONLY populate this when the user query involves TWO distinct elements interacting in the network:\n"
            "1. Pathfinding: The physical destination (e.g., from origin 'Lobby' to target 'Master Bedroom').\n"
            "2. Resilience/Isolation (BOTTLENECK): The element being blocked, removed, or isolated, IF an anchor "
            "is already provided in 'reference_space_name' (e.g., 'unreachable from hallway if bathroom is blocked' "
            "-> reference_space_name='hallway', target_space_name='bathroom')."
        )
    )
    
    location: Optional[str] = Field(
        None, 
        description=(
            "CRITICAL: The building storey, level, or floor ONLY (e.g., 'Ground Floor', 'Level 1', 'Level 2', 'Roof'). "
            "STRICT WARNING: NEVER pass room, space, or functional zone names (e.g., 'bedroom', 'kitchen', 'corridor', 'utility') into this field. "
            "Space/room names MUST strictly go to `reference_space_name` or `target_space_name`.")
        )

    properties: Optional[List[str]] = Field(
        default_factory=list, 
        description=(
            "CRITICAL: List of requested specific element-level properties or global dimensions to retrieve or filter by. "
            "If the user mentions terms like 'area', 'volume', 'height', or asks for conditions/filters "
            "based on overall dimensions (e.g., 'more than 5 square meters'), YOU MUST explicitly add the property name "
            "here (e.g., ['Area'] or ['Volume']). NEVER leave this empty if an element-level metric is mentioned.\n"
            
            "STRICT NEGATIVE CONSTRAINT (IF/THEN RULE):\n"
            "- IF the query asks about the dimension of a MATERIAL, a LAYER, or uses a relative pronoun/reference "
            "pointing to a layer (e.g., 'thickness of that layer', 'its thickness', 'insulation width'), "
            "THEN YOU MUST EXCLUDE 'Thickness' or 'Width' from this list!\n"
            "- REASON: Layer-specific dimensions are internal material attributes, NOT global element properties. "
            "They are automatically extracted via 'material_filter' and 'fetch_materials'.\n"
            "- ONLY include 'Thickness' here if the user explicitly requests the TOTAL, OVERALL, or COMPOSITE thickness "
            "of the structural element itself (e.g., 'total thickness of the wall', 'overall slab thickness')."
        )
    )

    @field_validator('properties', mode='before')
    @classmethod
    def prevent_layer_thickness_in_properties(cls, v: Optional[List[str]]) -> Optional[List[str]]:
       
        if not v:
            return v
            
        forbidden_layer_terms = {'thickness', 'layer thickness'}
        
        filtered_properties = [
            prop for prop in v 
            if prop.lower().strip() not in forbidden_layer_terms
        ]
        
        return filtered_properties

    
    topology_relation: TopologyRelation = Field(
        default=TopologyRelation.NONE,
        description=(
            "CRITICAL TOPOLOGY RULE: Choose the exact spatial relationship based on user intent:\n"
            "CRITICAL: If the question does NOT ask for paths, adjacencies, or connectivity, "
            "you MUST explicitly pass 'NONE'. NEVER pass an empty string ''."
          
            "- 'SHORTEST_PATH': Sequential multi-step routing, pathfinding, and macro-structural network depth analysis."
            "Select this in three major structural scenarios:\n"
            "  1) Point-to-Point Traversal: When the query explicitly or implicitly asks for the exact sequence of spaces, "
            "shortest route, or the specific number of physical barriers/interventions (e.g., counting doors, steps, boundaries) "
            "required to transition between distinct locations.\n"
            "  2) Bounded Reachability & Depth Constrained Queries: When evaluating which spaces are reachable within a specific "
            "threshold or limit of barriers (e.g., phrases like 'without passing through more than X doors', 'within X steps from', "
            "or 'accessible up to X transitions'). Any query requiring a cumulative count of links or doors across a path "
            "MUST use 'SHORTEST_PATH'.\n"
            "  3) Global/Macro Spatial Organization: When the query requests an evaluation of the global privacy hierarchy, "
            "topological depth matrix, spatial sequencing, or overall accessibility gradients of the entire plan (either from a "
            "designated anchor like an entrance/lobby or as an unanchored global network configuration).\n"
            "  CRITICAL GUARDRAIL: NEVER select 'SHORTEST_PATH' for immediate, 1-step direct neighborhood checks where no cumulative "
            "path depth or threshold is specified. Do NOT use it for calculating mathematical hub importance or network fragmentation "
            "resilience (use 'CENTRALITY', 'BOTTLENECK', or 'CRITICAL_ROUTE').\n\n"
            
            "- 'ADJACENT': Pure topological adjacency or abstract network connectivity BETWEEN SPATIAL ENTITIES (e.g., IfcSpace, rooms, zones). "
            "Select this ONLY when the user is querying about neighboring rooms or adjacent spatial volumes (e.g., 'which rooms are next to the kitchen', 'find spaces adjacent to the lobby'). "
            "CRITICAL GUARDRAIL: NEVER select 'ADJACENT' if the user's target element is a physical, structural, or architectural component "
            "(such as walls, partitions, slabs, columns, or doors) that separates, divides, or encloses a space. Physical dividers that form the "
            "architectural shell are handled via containment boundaries, not the space-to-space circulation graph.\n"
            
            "- 'DIRECT_ACCESS': For spaces with open boundaries/no doors.\n"
            
            "- 'DOOR_ACCESS': For spaces connected specifically by a door.\n"
            
            "- 'ANY_ACCESS': Strictly reserved for physical human circulation and spatial connectivity. "
            "Use this ONLY when the query inquires about the ability to move or navigate "
            "between spaces, representing the logical union of both [ACCESS_BY_DOOR] "
            "and [OPEN_ACCESS] relations (e.g., transitions, pathways, or adjacent traversals). "
            "CRITICAL: NEVER select 'ANY_ACCESS' for spatial containment, architectural shells, "
            "or building elements enclosed within a room. If the user describes fixtures, "
            "components, or structural elements located inside or bounding a space (such as "
            "components embedded in walls, floors, or openings), it is a property or containment "
            "filtering task, NOT a circulation topology relation."
            

            "- 'NONE': STANDARD SPATIAL CONTAINMENT AND PHYSICAL BOUNDARY SHELL QUERIES. Select 'NONE' anytime the user is looking for "
            "physical architectural elements (e.g., walls, partitions, slabs, ceilings, doors) that bound, enclose, partition, or separate "
            "a reference space from its surroundings, or elements located inside a room. This ensures that queries regarding the physical "
            "enclosure, structural barriers, or bounding shells of a space are routed to the Space-to-Element boundary pipeline (e.g., BOUNDED_BY relation) "
            "rather than the abstract spatial network graph.\n\n"
            

            "- 'CENTRALITY': Global flow, network integration, and traffic prominence. Select when the query focuses on identifying high-traffic hubs, primary circulation anchors, major thoroughfares, or spaces that possess the highest continuous movement potential and global interconnectedness based on mathematical index scores (e.g., betweenness, closeness, or degree). Choose this when the user is searching for 'busy', 'integrated', or 'strategically central' nodes that facilitate high transit volumes, without implying that their closure would physically split or fragment the network structure. "
            
            "- 'BOTTLENECK': Topological resilience, single points of failure, and graph fragmentation. Select when the query focuses on network vulnerability, critical transit thresholds, choke points, or articulation points (cut-vertices) whose closure, removal, blockage, or compromise causes downstream ISOLATION, UNREACHABILITY, or complete physical disconnection of graph components. Choose this whenever the core intent is to identify structural bridge nodes that uniquely connect separate zones, where the loss of that single entity breaks network continuity and fragments the global graph topology."
            
            "- 'CRITICAL_ROUTE': Multi-point relational vulnerability. Select ONLY when the user names TWO distinct "
            "terminal locations (a clear Source and a clear Destination) and asks whether the explicit route strictly "
            "between those two specific anchors will be severed by removing a third intermediate element. REQUIRES BOTH "
            "origin/reference and target space parameters to be explicitly provided; otherwise, default to 'BOTTLENECK'."
        )
    )
    
    condition: Optional[str] = Field(
        None,
        description=(
            "The comparison condition for properties or material layers (e.g., '> 3.1', '= True'). "
            "CRITICAL UNIT RULE: You MUST convert all physical dimensions to METERS (SI Units) before filling this. "
            "Examples: '5cm' MUST become '> 0.05', '50mm' MUST become '= 0.05', '200mm' MUST become '> 0.2'. "
            "Never pass raw centimeter or millimeter values as plain numbers."
        )
    )

    fetch_materials: bool = Field(
        default=False,
        description=(
            "Controls OUTPUT data. Set to True ONLY if: "
            "1) The user explicitly asks to RETRIEVE/read material details, layer structure, or composition in the final answer (e.g., 'What is it made of?', 'How thick is it?'). "
            "2) The user applies a numerical condition or mathematical filter on material/layer thickness (e.g., 'thickness > 3cm', 'air layer thicker than 0.02m'). "
            "WARNING: Do NOT set this to True just because a material name is mentioned in the prompt. "
            "CRITICAL RULE: If the user ONLY wants to filter elements by a material name without asking for details or thickness constraints (e.g., 'Find all concrete walls'), you MUST leave this False."
        )
    )
    
    material_filter: Optional[str] = Field(
        None,
        description=(
            "Controls FILTERING (WHERE clause). You MUST extract and provide the core material or layer noun here ANYTIME the user "
            "restricts their search to elements containing a specific material or layer type. "
            "CRITICAL: In this system, ANY layer within an element's assembly is considered a 'material'. "
            "This includes physical materials (e.g., 'plaster', 'wood', 'concrete', 'brick', 'glass') "
            "AS WELL AS functional or void layers (e.g., 'air', 'insulation', 'membrane', 'gap'). "
            "Provide only the base noun (e.g., 'air', 'plaster', 'insulation'). "
            "CRITICAL RULE: Always delegate material/layer filtering to the database using this argument. "
            "NEVER skip this argument to manually filter results in memory later."
        )
    )
