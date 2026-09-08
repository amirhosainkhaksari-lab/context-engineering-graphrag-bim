from typing import Dict, List, Any

from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

from .config import (
    NEO4J_URI,
    NEO4J_USERNAME,
    NEO4J_PASSWORD,
    EMBEDDINGS_MODEL_PATH,
)
from .ifc_processing import sanitize_properties


def create_graph_in_neo4j(
    nodes_dict: Dict[str, Dict[str, Any]],
    edges_data: List[Dict[str, Any]],
) -> None:
    """
    Materialize normalized BIM entities and relationships
    as a Neo4j Property Graph.
    """

    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )

    embeddings_model = SentenceTransformer(EMBEDDINGS_MODEL_PATH)

    try:
        with driver.session() as session:

            # ---------------------------------------------------------
            # 1. Materialize BIM entity nodes
            # ---------------------------------------------------------
            for node_id, node in nodes_dict.items():

                label = node.get("label", "UnknownElement")

                raw_props = dict(node)

                # Flatten nested property dictionaries where required.
                if isinstance(raw_props.get("properties"), dict):
                    raw_props.update(raw_props.pop("properties"))

                # Build searchable semantic text.
                search_parts = []

                ignore_keys = {
                    "guid",
                    "search_text",
                    "ifc_id",
                    "unit_scale",
                    "label",
                    "bbox_dimensions",
                    "global_centroid",
                    "key"
                }

                for key, value in raw_props.items():
                    if (
                        key in ignore_keys
                        or value in [None, "None", [], {} , ""]
                    ):
                        continue

                    search_parts.append(f"{key}: {value}")

                raw_props["search_text"] = ", ".join(search_parts)
                raw_props["id"] = str(node_id)

                # Sanitize nested properties before writing to Neo4j.
                final_props = sanitize_properties(raw_props)

                # Generate semantic embedding for searchable node content.
                search_text = final_props.get("search_text")

                if search_text:
                    vector = embeddings_model.encode(search_text).tolist()
                    final_props["embedding"] = vector

                query = f"""
                MERGE (n:{label} {{id: $node_id}})
                SET n = $props
                """

                session.run(
                    query,
                    node_id=str(node_id),
                    props=final_props,
                )

            # ---------------------------------------------------------
            # 2. Materialize normalized IFC relationships
            # ---------------------------------------------------------
            for edge in edges_data:

                source_id = str(edge.get("from"))
                target_id = str(edge.get("to"))
                edge_label = edge.get("label", "RELATED_TO")

                edge_props = {}

                if edge.get("rel_type"):
                    edge_props["rel_type"] = edge["rel_type"]

                if edge.get("rel_guid"):
                    edge_props["rel_guid"] = edge["rel_guid"]

                if edge.get("rel_ifc_id"):
                    edge_props["rel_ifc_id"] = edge["rel_ifc_id"]

                properties_dict = edge.get("properties", {})

                if isinstance(properties_dict, dict):
                    edge_props.update(properties_dict)

                cleaned_dict = {
                    key: value
                    for key, value in edge_props.items()
                    if value not in [{}, None, [], ""]
                }

                ignore_relationship_keys = {
                    "rel_ifc_id",
                    "rel_guid",
                    "list_id",
                    "layer_set_id",
                    "layer_id",
                }

                searchable_relationship_props = []

                for key, value in edge_props.items():
                    if (
                        key in ignore_relationship_keys
                        or value in [{}, None, [], ""]
                    ):
                        continue

                    searchable_relationship_props.append(
                        f"{key}: {value}"
                    )

                relationship_search_text = ", ".join(
                    searchable_relationship_props
                )

                query = f"""
                MATCH (a {{id: $source_id}})
                MATCH (b {{id: $target_id}})
                CREATE (a)-[r:{edge_label}]->(b)
                SET r.search_text = $search_text,
                    r += $properties
                """

                session.run(
                    query,
                    source_id=source_id,
                    target_id=target_id,
                    search_text=relationship_search_text,
                    properties=cleaned_dict,
                )

            # ---------------------------------------------------------
            # 3. Add searchable node label
            # ---------------------------------------------------------
            session.run(
                "MATCH (n) SET n:SearchableNode"
            )

            # ---------------------------------------------------------
            # 4. Full-text index
            # ---------------------------------------------------------
            session.run(
                """
                CREATE FULLTEXT INDEX BIMElement_fulltext_index
                IF NOT EXISTS
                FOR (n:SearchableNode)
                ON EACH [n.search_text]
                """
            )

            # ---------------------------------------------------------
            # 5. Vector index
            # ---------------------------------------------------------
            session.run(
                """
                CREATE VECTOR INDEX BIMElement_embedding_index
                IF NOT EXISTS
                FOR (n:SearchableNode)
                ON (n.embedding)
                OPTIONS {
                    indexConfig: {
                        `vector.dimensions`: 384,
                        `vector.similarity_function`: 'cosine'
                    }
                }
                """
            )

            # ---------------------------------------------------------
            # 6. Entity identifier index
            # ---------------------------------------------------------
            session.run(
                """
                CREATE INDEX node_id_index
                IF NOT EXISTS
                FOR (n:SearchableNode)
                ON (n.id)
                """
            )

            # ---------------------------------------------------------
            # 7. Basic materialization validation
            # ---------------------------------------------------------
            db_nodes_count = session.run(
                "MATCH (n) RETURN count(n) AS count"
            ).single()["count"]

            db_edges_count = session.run(
                "MATCH ()-[r]->() RETURN count(r) AS count"
            ).single()["count"]

            print(
                f"Python nodes: {len(nodes_dict)} | "
                f"Neo4j nodes: {db_nodes_count}"
            )

            print(
                f"Input relationships: {len(edges_data)} | "
                f"Neo4j relationships: {db_edges_count}"
            )

    finally:
        driver.close()
