from neo4j import GraphDatabase

@tool(args_schema=BIMQuerySchema)
def execute_master_bim_query(**kwargs) -> str:
    """
    Master BIM (Building Information Modeling) and IFC Graph Database Query Tool.
    
    ALWAYS use this tool when the user asks questions about the building model, architectural elements, 
    spatial configurations, materials, or properties. This tool connects to a Neo4j graph database 
    containing IFC data and operates on a DATA-DRIVEN schema.

    ======================================================================
    CRITICAL INSTRUCTION: OPERATIONAL SEMANTICS FOR SPATIAL REASONING
    ======================================================================
    When analyzing topological spatial queries, STRICTLY base your interpretation ONLY on the metrics 
    provided in the tool output. Do not hallucinate metrics that are not present.

    A. Point-to-Point Metrics (Local Pathfinding between specific spaces):
       1. Total Depth (Steps): The shortest-path distance between a specific origin and destination.
          - Interpretation: Lower depth indicates direct, immediate access. Higher depth indicates indirect, segregated access.
       2. Doors to cross: The exact number of physical barriers on a specific path.
          - Interpretation: 0 doors -> Open, continuous access. 1+ doors -> Controlled, restricted, or private access.

    B. Global Network Metrics (Overall spatial network analysis):
       3. Mean Topological Depth (MTD): Average distance from one space to ALL other spaces.
          - Interpretation: Lower MTD -> High spatial integration. Higher MTD -> High spatial segregation.
       4. Average Doors to Cross (ADC): Average doors crossed to reach ALL other spaces.
       5. Betweenness Centrality: Fraction of shortest paths passing through a space (Circulation hub).

    REASONING FRAMEWORK:
    1. Look at the retrieved data.
    2. If the data provides point-to-point paths (Total Depth, Doors to cross), evaluate LOCAL connectivity and physical access control.
    3. ONLY discuss Global Metrics (MTD, Betweenness, etc.) if those exact terms and values explicitly appear in the tool output (e.g., under a "Global Analysis" output).
    4. NEVER invent or deduce MTD or Centrality from point-to-point data alone.
    ======================================================================
    """
    query_data = BIMQuerySchema(**kwargs)
    
    element_concept = query_data.element_type
    target_name = query_data.target_element_name

    query_data = BIMQuerySchema(**kwargs)
    
    element_concept = query_data.element_type
    target_name = query_data.target_element_name
    ref_space = query_data.reference_space_name
    target_space = getattr(query_data, 'target_space_name', None)
    topology_val = getattr(query_data.topology_relation, 'value', query_data.topology_relation)
    loc = query_data.location
    props = query_data.properties
    topology = query_data.topology_relation
    condition = query_data.condition
    ifc_classes_to_search = []
    
    if element_concept:
        raw_classes = map_concept_to_ifc_classes(element_concept)
        
        if not raw_classes:
            return f"I couldn't identify the standard BIM class for '{element_concept}'."
            
        concept_words = element_concept.lower().split()
        
        for cls in raw_classes:
            cls_lower = cls.lower()
            if any(word in cls_lower for word in concept_words):
                ifc_classes_to_search.append(cls)
                
        if not ifc_classes_to_search:
            ifc_classes_to_search = raw_classes
            

    match_clauses = []
    where_clauses = []
    optional_matches = []
    returns = ["target.name AS TargetName", "labels(target)[0] AS TargetType"]
    params = {}


    is_space_query = element_concept == "space" or any(cls in ifc_classes_to_search for cls in ["IfcSpace"])
    is_topo_query = topology_val and topology_val not in ["NONE", "", None]

   
    # ==========================================================
    # 2. (Topology/Connectivity Pipeline)
    # ==========================================================
    if is_topo_query:
        rel_map = {
            "ADJACENT": "OPEN_ACCESS|ACCESS_BY_DOOR|ADJACENT_WALL",
            "DIRECT_ACCESS" : "OPEN_ACCESS",        
            "DOOR_ACCESS" : "ACCESS_BY_DOOR",
            "ANY_ACCESS": "OPEN_ACCESS|ACCESS_BY_DOOR"
        }
        relation_type = rel_map.get(topology_val, "OPEN_ACCESS|ACCESS_BY_DOOR|ADJACENT_WALL")
        
        if topology_val == "BOTTLENECK":
            import uuid
            
            bottleneck_filters = []
            if loc: 
                bottleneck_filters.append(f"toLower(currentStoreyName) CONTAINS toLower('{loc}')")
          
            blocked_term = target_space or target_name or element_concept
            anchor_term = ref_space 
            
            is_specific_target = bool(blocked_term and blocked_term.lower() not in ["space", "room", "building", "zone"])

            # ====================================================================
            # (Graph Cut & Reachability Analysis)
            # ====================================================================
                
            if is_specific_target:
             
                where_clause_blocked = f"WHERE toLower(b.name) CONTAINS toLower('{blocked_term}')"
                
                if anchor_term:
                    anchor_condition = f"WHERE toLower(anchor.name) CONTAINS toLower('{anchor_term}')"
                else:
                    anchor_condition = "WHERE (toLower(anchor.name) CONTAINS 'foyer' OR toLower(anchor.name) CONTAINS 'lobby' OR toLower(anchor.name) CONTAINS 'entrance')"

                cypher_query = f"""
                MATCH (b:IfcSpace)
                {where_clause_blocked}
                WITH collect(b) AS blocked_nodes
                
                OPTIONAL MATCH (anchor:IfcSpace)
                {anchor_condition}
                WITH blocked_nodes, collect(DISTINCT anchor) AS anchors
                
                OPTIONAL MATCH (fallback:IfcSpace)-[:SPATIAL_AGGREGATES]-(st:IfcBuildingStorey)
                WHERE toLower(st.name) CONTAINS 'level 1'
                WITH blocked_nodes, anchors, collect(DISTINCT fallback) AS fallbacks
                
                WITH blocked_nodes, 
                     CASE WHEN size(anchors) > 0 THEN anchors[0] ELSE fallbacks[0] END AS main_anchor
                
                WHERE main_anchor IS NOT NULL
                
                MATCH (target:IfcSpace)
                WHERE NOT target IN blocked_nodes AND target <> main_anchor
                
                
                AND EXISTS {{
                    MATCH p = shortestPath((target)-[:OPEN_ACCESS|ACCESS_BY_DOOR*]-(main_anchor))
                }}
                
                AND NOT EXISTS {{
                    MATCH p=(target)-[:OPEN_ACCESS|ACCESS_BY_DOOR*]-(main_anchor)
                    WHERE NONE(n IN nodes(p) WHERE n IN blocked_nodes)
                }}
                
                OPTIONAL MATCH (target)-[:SPATIAL_AGGREGATES]-(storey:IfcBuildingStorey)
                
                RETURN target.name AS TargetName, 
                       'Isolated Space (Unreachable Component)' AS TargetType,
                       COALESCE(storey.name, 'Unknown_Level') AS StoreyName,
                       [{{
                           neighbor: '{blocked_term} (Multiple Sub-Nodes)',
                           relation: 'GLOBAL_PATH_SEVERED',
                           impact: 'COMPLETELY ISOLATED (Lost access to anchor: ' + main_anchor.name + ')'
                       }}] AS BottleneckNeighbors
                ORDER BY StoreyName DESC, TargetName ASC
                """
            else:
                # ====================================================================
                # (Articulation Points)
                # ====================================================================
                graph_name = f"topo_art_{uuid.uuid4().hex}"
                where_clause = f"WHERE {' AND '.join(bottleneck_filters)}" if bottleneck_filters else ""

                cypher_query = f"""
                CALL gds.graph.project(
                    '{graph_name}',
                    'IfcSpace',
                    {{
                        OPEN_ACCESS: {{ orientation: 'UNDIRECTED' }},
                        ACCESS_BY_DOOR: {{ orientation: 'UNDIRECTED' }}
                    }}
                )
                YIELD graphName
        
                CALL gds.articulationPoints.stream(graphName)
                YIELD nodeId
                WITH collect(nodeId) AS results, graphName
        
                CALL gds.graph.drop(graphName) YIELD graphName AS dropped
        
                UNWIND results AS nId
                MATCH (target:IfcSpace) WHERE id(target) = nId
                
                OPTIONAL MATCH (target)-[:SPATIAL_AGGREGATES]-(s:IfcBuildingStorey)
                WITH target, coalesce(s.name, 'Unknown_Level') AS currentStoreyName
                
                {where_clause}
                
                OPTIONAL MATCH (target)-[:OPEN_ACCESS|ACCESS_BY_DOOR]-(all_neighbors:IfcSpace)
                WITH target, currentStoreyName, count(all_neighbors) AS nodeDegree
                
                OPTIONAL MATCH (target)-[r:OPEN_ACCESS|ACCESS_BY_DOOR]-(neighbor:IfcSpace)
                WITH target, currentStoreyName, nodeDegree, neighbor, type(r) AS relType
                
                WITH target, currentStoreyName,
                     collect({{
                         neighbor: coalesce(neighbor.name, 'None'), 
                         relation: coalesce(relType, 'None'), 
                         impact: CASE 
                            WHEN toLower(target.name) CONTAINS 'stair' OR toLower(target.name) CONTAINS 'elevator' 
                                THEN 'Critical Vertical Articulation Point'
                            WHEN nodeDegree <= 2 
                                THEN 'Local Accessibility Articulation Point'
                            ELSE 'Horizontal Circulation Articulation Point'
                         END
                     }}) AS neighbors
        
                RETURN target.name AS TargetName, 
                       'Bottleneck / Articulation Point' AS TargetType,
                       currentStoreyName AS StoreyName,
                       neighbors AS BottleneckNeighbors
                """
            
            match_clauses = []
#=====================================================================================================
            
        if topology_val == "CENTRALITY":
            cypher_query = f"""
            MATCH p = allShortestPaths((s1:IfcSpace)-[:{relation_type}*]-(s2:IfcSpace))
            WHERE elementId(s1) < elementId(s2)
            
            WITH s1, s2, count(p) AS total_shortest_paths, collect(p) AS paths
            
            UNWIND paths AS path
            UNWIND nodes(path)[1..-1] AS space
            
            WITH space, sum(1.0 / total_shortest_paths) AS betweenness_score
            
            OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(space)
            
            RETURN space.name AS TargetName, 
                   toFloat(betweenness_score) AS Score, 
                   'High Betweenness Centrality Node' AS TargetType,
                   COALESCE(storey.name, 'Unknown_Level') AS StoreyName
            ORDER BY Score DESC 
            LIMIT 10
            """
            match_clauses = []

#=========================================================================================================        
        elif topology_val == "CRITICAL_ROUTE":
            if not ref_space or not target_space:
                return "Error: Both reference_space_name and target_space_name are required for finding a critical route."
                
            match_clauses.append(f"""
                MATCH (startSpace:IfcSpace), (endSpace:IfcSpace)
                WHERE (toLower(startSpace.name) CONTAINS toLower($ref_space) OR toLower(startSpace.search_text) CONTAINS toLower($ref_space))
                  AND (toLower(endSpace.name) CONTAINS toLower($target_space) OR toLower(endSpace.search_text) CONTAINS toLower($target_space))
                
                MATCH path = shortestPath((startSpace)-[:OPEN_ACCESS|ACCESS_BY_DOOR*]-(endSpace))
                WITH startSpace, endSpace, nodes(path) AS shortestNodes
                
                MATCH allPaths = (startSpace)-[:OPEN_ACCESS|ACCESS_BY_DOOR*]-(endSpace)
                WITH shortestNodes, collect(nodes(allPaths)) AS pathsList, startSpace, endSpace
                
                UNWIND shortestNodes AS target
                WITH target, pathsList, startSpace, endSpace
                WHERE target <> startSpace AND target <> endSpace
                  AND all(p IN pathsList WHERE target IN p)
                
                WITH target
            """)
            
            params["ref_space"] = ref_space
            params["target_space"] = target_space
            
            returns.clear()  
            returns.extend(["target.name AS TargetName", "'Critical Node in Route' AS TargetType"])
#======================================================================================================================
        
        elif topology_val == "SHORTEST_PATH":
          
            if ref_space and target_space:
                match_clauses.append("""
                    MATCH (start:IfcSpace), (target:IfcSpace)
                    WHERE (toLower(start.name) CONTAINS toLower($ref_space) OR toLower(start.search_text) CONTAINS toLower($ref_space))
                      AND (toLower(target.name) CONTAINS toLower($target_space) OR toLower(target.search_text) CONTAINS toLower($target_space))
                    
                    MATCH path = shortestPath((start)-[:OPEN_ACCESS|ACCESS_BY_DOOR*]-(target))
                    OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target)
                    
                    WITH target, storey, path,
                         [n IN nodes(path) WHERE 'IfcSpace' IN labels(n) | coalesce(n.name, 'Unknown')] AS SpacesInPath,
                         [r IN relationships(path) | type(r)] AS ConnectionTypes
                    
                    WITH target, storey, SpacesInPath, ConnectionTypes, length(path) AS TotalSteps,
                         size([rel IN ConnectionTypes WHERE rel = 'ACCESS_BY_DOOR']) AS DoorsToCross
                """)
                
                params["ref_space"] = ref_space
                params["target_space"] = target_space
                
                returns.extend([
                    "SpacesInPath AS Route", 
                    "ConnectionTypes", 
                    "DoorsToCross", 
                    "TotalSteps", 
                    "COALESCE(storey.name, 'N/A') AS StoreyName", 
                    "target.name AS SpaceName"
                ])
            
            # -----------------------------------------------------------------
      
            elif ref_space and not target_space:
                storey_filter = "AND toLower(storey.name) CONTAINS toLower($loc)" if loc else ""
                if loc:
                    params["loc"] = loc
                
                match_clauses.append(f"""
                    MATCH (start:IfcSpace)
                    WHERE (toLower(start.name) CONTAINS toLower($ref_space) OR toLower(start.search_text) CONTAINS toLower($ref_space))
                    
                    WITH start LIMIT 1
                    
                    MATCH (target:IfcSpace)
                    WHERE target <> start
                    
                    OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target)
                    WITH start, target, storey
                    WHERE 1=1 {storey_filter}
                    
                    MATCH path = shortestPath((start)-[:OPEN_ACCESS|ACCESS_BY_DOOR*]-(target))
                    
                    WITH target, storey, path,
                         [n IN nodes(path) WHERE 'IfcSpace' IN labels(n) | coalesce(n.name, 'Unknown')] AS SpacesInPath,
                         [r IN relationships(path) | type(r)] AS ConnectionTypes
                    
                    WITH target, storey, SpacesInPath, ConnectionTypes, length(path) AS TopologicalDepth,
                         size([rel IN ConnectionTypes WHERE rel = 'ACCESS_BY_DOOR']) AS BarriersCrossed
                """)
                
                params["ref_space"] = ref_space
                
                returns.extend([
                    "SpacesInPath AS Route", 
                    "ConnectionTypes", 
                    "BarriersCrossed AS DoorsToCross", 
                    "TopologicalDepth AS TotalSteps", 
                    "COALESCE(storey.name, 'N/A') AS StoreyName", 
                    "target.name AS SpaceName"
                ])

          
            # -----------------------------------------------------------------
       
            else:
                storey_filter = "AND toLower(storey.name) CONTAINS toLower($loc)" if loc else ""
                if loc:
                    params["loc"] = loc
                 
                match_clauses.append(f"""
                    MATCH (target:IfcSpace)
                    OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target)
                    WITH target, storey
                    WHERE 1=1 {storey_filter}
                     
                    MATCH (other:IfcSpace)
                    WHERE other <> target
                     
                    MATCH path = shortestPath((target)-[:OPEN_ACCESS|ACCESS_BY_DOOR*]-(other))
                     
                    WITH target, storey, 
                        avg(toFloat(length(path))) AS InstanceDepth,
                        avg(toFloat(size([rel IN relationships(path) WHERE type(rel) = 'ACCESS_BY_DOOR']))) AS InstanceBarriers
                     
                    WITH target.name AS SpaceName,
                        COALESCE(storey.name, 'N/A') AS StoreyName,
                        avg(InstanceBarriers) AS AvgBarriers,
                        avg(InstanceDepth) AS MeanTopologicalDepth,
                        collect(target)[0] AS target,
                        collect(storey)[0] AS storey
                """)
                 
                returns.extend([
                    "['Global Analysis'] AS Route", 
                    "['AVERAGED'] AS ConnectionTypes", 
                    "round(AvgBarriers, 2) AS DoorsToCross", 
                    "round(MeanTopologicalDepth, 2) AS TotalSteps", 
                    "COALESCE(storey.name, 'N/A') AS StoreyName", 
                    "target.name AS SpaceName"
                 ])
            
        else: 
            match_clauses.append(f"""
                MATCH (ref:IfcSpace)-[rel:{relation_type}]-(target:IfcSpace)
                WHERE (toLower(ref.name) CONTAINS toLower($ref_space) OR toLower(ref.search_text) CONTAINS toLower($ref_space))
                OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target)
                WITH target, storey, ref, rel
            """)
            params["ref_space"] = ref_space
            returns.extend(["ref.name AS ReferenceSpace", "type(rel) AS ConnectionType", "COALESCE(storey.name, 'N/A') AS StoreyName"])
#==================================================================================================================
    else:
        if is_space_query:
            if loc and ref_space:
                match_clauses.append("""
                    MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target:IfcSpace)
                    WITH target, storey
                """)
                where_clauses.append("toLower(storey.name) CONTAINS toLower($loc)")
                where_clauses.append("toLower(target.name) CONTAINS toLower($ref_space)")
                params["loc"] = loc
                params["ref_space"] = ref_space
            elif loc:
                match_clauses.append("""
                    MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target:IfcSpace)
                    WITH target, storey
                """)
                where_clauses.append("toLower(storey.name) CONTAINS toLower($loc)")
                params["loc"] = loc
            elif ref_space:
                match_clauses.append("""
                    MATCH (target:IfcSpace)
                    OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target)
                    WITH target, storey
                """)
                where_clauses.append("toLower(target.name) CONTAINS toLower($ref_space)")
                params["ref_space"] = ref_space
            else:
                match_clauses.append("""
                    MATCH (target:IfcSpace)
                    OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(target)
                    WITH target, storey
                """)
                
            returns.extend([
                "COALESCE(storey.name, 'N/A') AS StoreyName", 
                "COALESCE(target.name, 'N/A') AS SpaceName", 
                "COALESCE(target.guid, 'N/A') AS SpaceID",
                "COALESCE(target.community_id, 'N/A') AS CommunityID"  # <-- اضافه شود
            ])
    
        else: # Physical Elements
            if loc and ref_space:
                match_clauses.append("""
                    MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(space:IfcSpace)
                    MATCH (space)-[:BOUNDED_BY]-(target)
                    WITH target, storey, space
                """)
                where_clauses.append("toLower(storey.name) CONTAINS toLower($loc)")
                where_clauses.append("toLower(space.name) CONTAINS toLower($ref_space)")
                params["loc"] = loc
                params["ref_space"] = ref_space
            elif loc:
                match_clauses.append("""
                    MATCH (target)
                    OPTIONAL MATCH (target)-[:BOUNDED_BY]-(space:IfcSpace)
                    OPTIONAL MATCH (storey_from_space:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(space)
                    OPTIONAL MATCH (storey_direct:IfcBuildingStorey)-[:SPATIAL_AGGREGATES|CONTAINS_ELEMENTS]-(target)
                    WITH DISTINCT target, space, COALESCE(storey_from_space, storey_direct) AS storey
                """)
                where_clauses.append("toLower(storey.name) CONTAINS toLower($loc)")
                params["loc"] = loc
            elif ref_space:
                match_clauses.append("""
                    MATCH (space:IfcSpace)-[:BOUNDED_BY]-(target)
                    OPTIONAL MATCH (storey:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(space)
                    WITH target, storey, space
                """)
                where_clauses.append("toLower(space.name) CONTAINS toLower($ref_space)")
                params["ref_space"] = ref_space
            else:
                match_clauses.append("""
                    MATCH (target)
                    OPTIONAL MATCH (target)-[:BOUNDED_BY]-(space:IfcSpace)
                    OPTIONAL MATCH (storey_from_space:IfcBuildingStorey)-[:SPATIAL_AGGREGATES]->(space)
                    OPTIONAL MATCH (storey_direct:IfcBuildingStorey)-[:SPATIAL_AGGREGATES|CONTAINS_ELEMENTS]-(target)
                    WITH DISTINCT target, space, COALESCE(storey_from_space, storey_direct) AS storey
                """)
                
            returns.extend([
                "COALESCE(storey.name, 'N/A') AS StoreyName",
                "COALESCE(space.name, 'N/A') AS SpaceName"])

    # ==========================================================
    # 3. (Target Node) 
    # ==========================================================
    if ifc_classes_to_search:
        if not (is_topo_query and "IfcSpace" not in ifc_classes_to_search):
            where_clauses.append("any(label IN labels(target) WHERE label IN $ifc_classes)")
            params["ifc_classes"] = ifc_classes_to_search

    if target_name:
        clean_target = target_name.replace(" ", "").lower()
        where_clauses.append(
            "(toLower(target.name) CONTAINS toLower($target_name) OR "
            f"toLower(target.name) CONTAINS '{clean_target}' OR "
            "toLower(target.search_text) CONTAINS toLower($target_name))"
        )
        params["target_name"] = target_name

    # ==========================================================
    # 4. (Properties & Conditionals) 
    # ==========================================================
    if props:
        prop_filters_exist = []
        for i, p in enumerate(props):
            param_key = f"prop_{i}"
            params[param_key] = p
            prop_filters_exist.append(f"toLower(pset.search_text) CONTAINS toLower(${param_key})")
        
        where_clauses.append(f"""
        EXISTS {{
            MATCH (target)-[:HAS_PROPERTYSETS]->(pset)
            WHERE {" OR ".join(prop_filters_exist)}
        }}
        """)
        
        extraction_filters = " OR ".join([f"toLower(p.search_text) CONTAINS toLower($prop_{i})" for i in range(len(props))])
        returns.append(f"[(target)-[:HAS_PROPERTYSETS]->(p) WHERE {extraction_filters} | p.search_text] AS FilteredProperties")
    else:
        returns.append("[] AS FilteredProperties")
    
    
    # ==========================================================
    # 5. (Materials) 
    # ==========================================================
    fetch_mats = getattr(query_data, 'fetch_materials', False)
    raw_mat_filter = getattr(query_data, 'material_filter', None)
    
    if fetch_mats or raw_mat_filter:
        if raw_mat_filter:
            tokens = [t.lower() for t in re.split(r'[\s_\-]+', raw_mat_filter) if t]
            
            dir_conditions = []
            type_conditions = []
            for i, token in enumerate(tokens):
                param_key = f"mat_token_{i}"
                params[param_key] = token
                dir_conditions.append(f"(toLower(m.name) CONTAINS ${param_key} OR toLower(m.search_text) CONTAINS ${param_key})")
                type_conditions.append(f"(toLower(m.name) CONTAINS ${param_key} OR toLower(m.search_text) CONTAINS ${param_key})")
            
            dir_where = " AND ".join(dir_conditions)
            type_where = " AND ".join(type_conditions)
            
            where_clauses.append(f"""
            (
                EXISTS {{
                    MATCH (target)-[:HAS_MATERIAL]->(m:Material)
                    WHERE {dir_where}
                }}
                OR 
                EXISTS {{
                    MATCH (target)-[:HAS_TYPE]->()-[:HAS_MATERIAL]->(m:Material)
                    WHERE {type_where}
                }}
            )
            """)
            
            returns.append(f"""
            ([(target)-[r:HAS_MATERIAL]->(m:Material) WHERE {dir_where} | {{
                RawLayerData: COALESCE(r.search_text, 'No Text'),
                Material: COALESCE(m.name, m.search_text, 'Unknown Material')
            }}] + 
            [(target)-[:HAS_TYPE]->()-[r:HAS_MATERIAL]->(m:Material) WHERE {type_where} | {{
                RawLayerData: COALESCE(r.search_text, 'No Text'),
                Material: COALESCE(m.name, m.search_text, 'Unknown Material')
            }}]) AS MaterialData
            """)
        else:
            returns.append("""
            ([(target)-[r:HAS_MATERIAL]->(m:Material) | {
                RawLayerData: COALESCE(r.search_text, 'No Text'),
                Material: COALESCE(m.name, m.search_text, 'Unknown Material')
            }] + 
            [(target)-[:HAS_TYPE]->()-[r:HAS_MATERIAL]->(m:Material) | {
                RawLayerData: COALESCE(r.search_text, 'No Text'),
                Material: COALESCE(m.name, m.search_text, 'Unknown Material')
            }]) AS MaterialData
            """)
