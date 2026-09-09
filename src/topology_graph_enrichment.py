from typing import Any, Dict, List, Tuple

import ifcopenshell
import ifcopenshell.geom
from neo4j import GraphDatabase
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USERNAME

GEOMETRY_SETTINGS = ifcopenshell.geom.settings()
GEOMETRY_SETTINGS.set(GEOMETRY_SETTINGS.USE_WORLD_COORDS, True)


def get_element_2d_footprint(element) -> Tuple[Any, float, float]:
    """
    Extract a 2D polygonal footprint and vertical extent
    from an IFC element's geometry.
    """
    try:
        shape = ifcopenshell.geom.create_shape(GEOMETRY_SETTINGS, element)
    except Exception:
        return None, None, None

    verts = shape.geometry.verts
    faces = shape.geometry.faces

    triangles = []
    z_coords = []

    for i in range(0, len(faces), 3):
        idx1, idx2, idx3 = faces[i], faces[i + 1], faces[i + 2]

        x1, y1, z1 = verts[idx1 * 3], verts[idx1 * 3 + 1], verts[idx1 * 3 + 2]
        x2, y2, z2 = verts[idx2 * 3], verts[idx2 * 3 + 1], verts[idx2 * 3 + 2]
        x3, y3, z3 = verts[idx3 * 3], verts[idx3 * 3 + 1], verts[idx3 * 3 + 2]

        triangles.append(Polygon([(x1, y1), (x2, y2), (x3, y3)]))
        z_coords.extend([z1, z2, z3])

    if not triangles:
        return None, None, None

    footprint = unary_union(triangles)
    if not footprint.is_valid:
        footprint = footprint.buffer(0)

    return footprint, min(z_coords), max(z_coords)


def get_spatial_relationships(
    spaces_dict: Dict[str, Dict[str, Any]],
    doors: List[Tuple[Any, float, float]],
    walls: List[Tuple[Any, float, float]],
) -> List[Dict[str, Any]]:
    """
    Derive geometry-based spatial accessibility relationships
    between IFC spaces.
    """
    spatial_relationships = []
    tolerance = 0.30
    guids = list(spaces_dict.keys())

    for i in range(len(guids)):
        for j in range(i + 1, len(guids)):
            g1, g2 = guids[i], guids[j]
            data1, data2 = spaces_dict[g1], spaces_dict[g2]

            s1_name_raw = str(data1["exact_name"]).strip()
            s2_name_raw = str(data2["exact_name"]).strip()

            s1_name = s1_name_raw.lower()
            s2_name = s2_name_raw.lower()

            poly1, poly2 = data1["poly"], data2["poly"]
            z1, z2 = data1["z_min"], data2["z_min"]

            # Floor and unit consistency
            same_floor = abs(z1 - z2) <= 0.5
            prefix1 = s1_name_raw[0].upper() if s1_name_raw else ""
            prefix2 = s2_name_raw[0].upper() if s2_name_raw else ""
            same_unit = prefix1 == prefix2

            # Rule-based special spatial pairs
            is_stair_hallway = ("stair" in s1_name and "hallway" in s2_name) or ("stair" in s2_name and "hallway" in s1_name)
            is_foyer_living = ("foyer" in s1_name and "living room" in s2_name) or ("foyer" in s2_name and "living room" in s1_name)
            is_hallway_utility = ("hallway" in s1_name and "utility" in s2_name) or ("hallway" in s2_name and "utility" in s1_name)
            is_utility_bathroom = ("utility" in s1_name and "bathroom" in s2_name) or ("utility" in s2_name and "bathroom" in s1_name)
            is_kitchen_living = ("kitchen" in s1_name and "living room" in s2_name) or ("kitchen" in s2_name and "living room" in s1_name)

            # Pair-specific constraints
            if is_foyer_living and not (same_unit and same_floor):
                is_foyer_living = False
            if is_hallway_utility and not (same_unit and same_floor):
                is_hallway_utility = False
            if is_utility_bathroom and not (same_unit and same_floor):
                is_utility_bathroom = False
            if is_kitchen_living and not (same_unit and same_floor):
                is_kitchen_living = False
            if is_stair_hallway and not same_unit:
                is_stair_hallway = False

            is_special_pair = (
                is_stair_hallway or is_foyer_living or is_hallway_utility or is_utility_bathroom or is_kitchen_living
            )

            if not same_floor and not is_special_pair:
                continue

            # Shared boundary analysis
            shared_line = poly1.buffer(tolerance).intersection(poly2.boundary)

            if not is_special_pair:
                if shared_line.is_empty or shared_line.length < 0.40:
                    continue

            shared_length = shared_line.length if not shared_line.is_empty else 0.0

            # Valid walls and doors at the current elevation
            valid_walls = [wall[0] for wall in walls if (wall[1] - 0.5) <= z1 <= wall[2]]
            valid_doors = [door[0] for door in doors if (door[1] - 0.5) <= z1 <= door[2]]

            # Door and wall coverage analysis
            if not shared_line.is_empty:
                has_door = any(
                    door.distance(poly1) < 0.15 and door.distance(poly2) < 0.15 and door.distance(shared_line) < 0.20
                    for door in valid_doors
                )
                wall_union = unary_union([wall.buffer(0.02) for wall in valid_walls]) if valid_walls else None
                wall_length = shared_line.intersection(wall_union).length if wall_union else 0.0
            else:
                has_door = False
                wall_length = 0.0

            coverage_ratio = min(wall_length / shared_length, 1.0) if shared_length > 0 else 0.0

            # Relationship classification
            if is_stair_hallway:
                relationship = "OPEN_ACCESS"
                info = "Forced: Cross-floor Open Access (Stair to Hallway)"
                coverage_ratio = 0.0
            elif is_foyer_living:
                relationship = "OPEN_ACCESS"
                info = "Forced: Partial Open Access (Foyer to Living Room)"
            elif is_kitchen_living:
                relationship = "OPEN_ACCESS"
                info = "Forced: Open Access (Kitchen to Living Room)"
            elif is_hallway_utility:
                relationship = "ADJACENT_WALL"
                info = "Forced: Adjacent Wall (Hallway to Utility)"
            elif is_utility_bathroom:
                relationship = "ACCESS_BY_DOOR"
                info = "Forced: Solid Wall Coverage (Utility to Bathroom)"
            elif has_door:
                relationship = "ACCESS_BY_DOOR"
                info = f"Connected via Door (Boundary: {shared_length:.2f}m)"
            elif coverage_ratio > 0.90:
                relationship = "ADJACENT_WALL"
                info = f"Solid Wall Coverage: {coverage_ratio:.1%}"
            elif coverage_ratio < 0.15:
                relationship = "OPEN_ACCESS"
                info = f"Pure Open Connection (No Wall: {shared_length:.2f}m)"
            else:
                relationship = "OPEN_ACCESS"
                info = f"Partial Open Access (Wall: {coverage_ratio:.1%}, Open: {shared_length * (1 - coverage_ratio):.2f}m)"

            spatial_relationships.append({
                "from": g1,
                "to": g2,
                "label": relationship,
                "properties": {
                    "info": info,
                    "coverage_ratio": coverage_ratio,
                },
            })

    return spatial_relationships


def add_spatial_relations_to_neo4j(spatial_relationships: List[Dict[str, Any]]) -> None:
    """
    Materialize geometry-derived spatial relationships
    in the existing Neo4j BIM knowledge graph.
    """
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )

    try:
        with driver.session() as session:
            created_count = 0

            for relationship in spatial_relationships:
                source_id = str(relationship["from"])
                target_id = str(relationship["to"])
                relationship_label = relationship["label"]
                properties = relationship.get("properties", {})

                query = f"""
                MATCH (a)
                WHERE a.id = $source_id OR a.guid = $source_id OR a.GlobalId = $source_id

                MATCH (b)
                WHERE b.id = $target_id OR b.guid = $target_id OR b.GlobalId = $target_id

                MERGE (a)-[r:{relationship_label}]->(b)
                SET r += $properties
                RETURN count(r) AS count
                """

                result = session.run(
                    query,
                    source_id=source_id,
                    target_id=target_id,
                    properties=properties,
                )
                record = result.single()

                if record and record["count"] > 0:
                    created_count += 1

            print(f"Spatial relationships added to Neo4j: {created_count}")

    finally:
        driver.close()
