from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class TopologyRelation(str, Enum):
    SHORTEST_PATH = "SHORTEST_PATH"
    ADJACENT = "ADJACENT"
    DIRECT_ACCESS = "DIRECT_ACCESS"
    DOOR_ACCESS = "DOOR_ACCESS"
    ANY_ACCESS = "ANY_ACCESS"
    NONE = "NONE"
    BOTTLENECK = "BOTTLENECK"
    CENTRALITY = "CENTRALITY"
    CRITICAL_ROUTE = "CRITICAL_ROUTE"


class BIMQuerySchema(BaseModel):

    element_type: str = Field(
        ...,
        description=(
            "The general category, class, or architectural subtype of the "
            "element (e.g., wall, beam, slab, sliding door, space, room, "
            "building storey). Always extract the most specific architectural "
            "category mentioned. If the user uses phrases like 'called "
            "[Category]', extract the category here. NOTE: When a query asks "
            "about spaces containing, hosting, or bounded by physical elements "
            "(e.g., walls, windows, doors), set element_type to the target "
            "physical element being evaluated or filtered, NOT 'space'."
        ),
    )

    target_element_name: Optional[str] = Field(
        None,
        description=(
            "STRICTLY for unique alphanumeric identifiers, instance names, "
            "or specific tags (e.g., Wall-01, Door_A, GUID_123). DO NOT use "
            "this field for general architectural concepts or sub-categories. "
            "Only populate this if the user specifies an exact, unique "
            "instance ID."
        ),
    )

    reference_space_name: Optional[str] = Field(
        None,
        description=(
            "CRITICAL: The primary focal space, subject of analysis, origin "
            "room, or functional zone. ALWAYS populate this field whenever a "
            "specific space/room name is mentioned in the query. This applies "
            "to single-space topological/accessibility analysis, spatial "
            "context queries, and origin-node pathfinding queries. Examples: "
            "'corridor', 'foyer', 'stair', 'living room', 'kitchen', "
            "'bathroom', 'office', 'bedroom'."
        ),
    )

    target_space_name: Optional[str] = Field(
        default=None,
        description=(
            "CRITICAL FOR MULTI-NODE QUERIES: The secondary or destination "
            "spatial entity. ONLY populate this when the user query involves "
            "two distinct elements interacting in the network. This includes "
            "pathfinding and resilience/isolation queries."
        ),
    )

    location: Optional[str] = Field(
        None,
        description=(
            "CRITICAL: The building storey, level, or floor ONLY "
            "(e.g., 'Ground Floor', 'Level 1', 'Level 2', 'Roof'). "
            "NEVER pass room, space, or functional-zone names into this field. "
            "Space/room names MUST be assigned to reference_space_name or "
            "target_space_name."
        ),
    )

    properties: Optional[List[str]] = Field(
        default_factory=list,
        description=(
            "CRITICAL: List of requested specific element-level properties "
            "or global dimensions to retrieve or filter by. If the user "
            "mentions terms such as area, volume, height, or conditions based "
            "on overall dimensions, explicitly add the corresponding "
            "property name here. Layer-specific dimensions such as material "
            "thickness are excluded because they are handled through "
            "material_filter and fetch_materials. Only include Thickness when "
            "the user explicitly requests the total, overall, or composite "
            "thickness of the structural element itself."
        ),
    )

    @field_validator("properties", mode="before")
    @classmethod
    def prevent_layer_thickness_in_properties(
        cls,
        value: Optional[List[str]],
    ) -> Optional[List[str]]:
        if not value:
            return value

        forbidden_layer_terms = {
            "thickness",
            "layer thickness",
        }

        return [
            prop
            for prop in value
            if prop.lower().strip() not in forbidden_layer_terms
        ]

    topology_relation: TopologyRelation = Field(
        default=TopologyRelation.NONE,
        description=(
            "CRITICAL TOPOLOGY RULE: Choose the exact spatial relationship "
            "based on user intent. If the question does NOT ask for paths, "
            "adjacencies, or connectivity, explicitly pass 'NONE'. "
            "'SHORTEST_PATH' is used for sequential routing, pathfinding, "
            "bounded reachability, depth-constrained queries, and global "
            "spatial organization analysis. "
            "'ADJACENT' is used for pure spatial adjacency between spaces. "
            "'DIRECT_ACCESS' represents open-boundary accessibility without "
            "doors. 'DOOR_ACCESS' represents door-mediated accessibility. "
            "'ANY_ACCESS' represents general human circulation through both "
            "open and door-mediated connections. "
            "'NONE' is used for standard spatial containment and physical "
            "boundary queries. "
            "'CENTRALITY' represents network-flow importance such as "
            "betweenness-based circulation prominence. "
            "'BOTTLENECK' represents network vulnerability and articulation "
            "points whose removal can fragment the accessibility graph. "
            "'CRITICAL_ROUTE' is reserved for route-specific vulnerability "
            "between explicitly specified source and destination spaces."
        ),
    )

    condition: Optional[str] = Field(
        None,
        description=(
            "The comparison condition for properties or material layers "
            "(e.g., '> 3.1', '= True'). Physical dimensions MUST be converted "
            "to meters (SI units) before being stored in this field. Examples: "
            "'5cm' becomes '> 0.05', '50mm' becomes '= 0.05', and '200mm' "
            "becomes '> 0.2'."
        ),
    )

    fetch_materials: bool = Field(
        default=False,
        description=(
            "Controls material-related output. Set to True when the user "
            "explicitly requests material or layer details, or when a "
            "numerical condition applies to material/layer thickness. "
            "Do not set to True merely because a material name is mentioned "
            "when material details are not requested."
        ),
    )

    material_filter: Optional[str] = Field(
        None,
        description=(
            "Controls material filtering in graph retrieval. Extract the "
            "core material or layer noun whenever the user restricts the "
            "search to elements containing a specific material or layer type. "
            "This includes physical materials such as plaster, wood, concrete, "
            "brick, and glass, as well as functional or void layers such as "
            "air, insulation, membrane, and gap. Always delegate material "
            "filtering to the database through this field."
        ),
    )
