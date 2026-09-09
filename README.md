# Context Engineering GraphRAG for BIM Reasoning

Research prototype for reliable LLM-based reasoning over IFC-derived BIM knowledge graphs using Context Engineering and GraphRAG.

## Key Components

### 1. IFC Processing

The BIM model is processed using IfcOpenShell to extract relevant IFC entities, semantic attributes, geometric descriptors, quantitative information, materials, property sets, type definitions, and native IFC relationships.

Dimensional and quantitative values are normalized according to the IFC project unit context before graph materialization.

### 2. BIM Knowledge Graph Construction

The extracted BIM information is materialized as a Neo4j Property Graph. IFC entities are represented as graph nodes, while normalized IFC relationships are represented as typed directed relationships.

The resulting graph integrates spatial hierarchies, semantic attributes, material information, and normalized IFC relationships into a queryable representation for subsequent retrieval operations.

### 3. Spatial Accessibility Graph Enrichment

Because native IFC relationships do not explicitly represent all navigable spatial relationships, additional accessibility relations are derived from the geometric configuration of spaces and their surrounding walls, doors, and openings.

The enrichment layer introduces:

- `OPEN_ACCESS`
- `ACCESS_BY_DOOR`
- `ADJACENT_WALL`

These derived relationships form an additional topological layer over the IFC-derived graph and support topology-aware retrieval and graph analysis.

### 4. Structured BIM Query Interpretation

Natural-language BIM queries are transformed into a structured BIM query schema using Pydantic-based validation and LLM tool calling.

The schema captures:

- target BIM entity
- target instance
- spatial references
- building location
- requested properties
- material constraints
- numerical conditions
- topology objectives

### 5. IFC Schema Alignment and Retrieval Specification

Architectural concepts extracted from the structured query are aligned with IFC entity classes using a local ChromaDB knowledge base containing IFC classes, semantic descriptions, and architectural synonyms.

Semantic similarity retrieval is combined with lexical consistency filtering and fallback handling. The resulting IFC-aligned classes are combined with the remaining structured query attributes to define a schema-aligned retrieval specification.

### 6. Query-Specific Graph Retrieval

The schema-aligned retrieval requirements are translated into dynamically assembled Cypher operations rather than a fixed graph query.

The retrieval layer supports:

- spatial containment and boundary retrieval
- property and quantity filtering
- material and layer retrieval
- accessibility analysis
- shortest-path routing
- anchored and global accessibility analysis
- betweenness centrality
- critical-route analysis
- bottleneck / articulation-point analysis

The retrieval process selectively acquires the BIM entities, relationships, attributes, material information, accessibility paths, and graph-derived evidence required by each query.

### 7. Evidence Consolidation and Context Assembly

Retrieved graph evidence is not passed directly to the language model. Instead, it is processed through query-specific validation, consolidation and integration, and context assembly.

This stage verifies attribute-level, numerical, and material constraints, removes redundant or overlapping representations, and integrates complementary evidence associated with the same BIM entities and spatial contexts.

The retained evidence is normalized into a structured, query-specific context containing the entity, spatial, property, material, and topology information required for grounded LLM reasoning.

### 8. Evidence-Grounded LLM Reasoning and Answer Generation

The BIM retrieval interface is exposed to the language model as a tool, separating graph-based evidence acquisition from final language-model reasoning.

The prototype uses a LangGraph ReAct-style agent with the BIM query tool. Retrieved BIM evidence is used as the basis for final answer generation, while tool calls, arguments, retrieved outputs, and token usage are logged for experimental analysis.

## Example Query

**User query**

> Q20. Which spaces larger than 20 m² are reachable from the foyer without passing through more than one door?.

**Structured query**

```json
{"properties": ["Area"],
  "element_type": "space",
  "reference_space_name": "foyer",
  "topology_relation": "SHORTEST_PATH",
  "condition": "> 20"}
```

The structured request is aligned with the IFC schema, translated into query-specific graph retrieval requirements, executed against the BIM knowledge graph, and returned as BIM-grounded evidence for final LLM reasoning.

## Graph Analytics

The topology-aware retrieval layer extends beyond direct relationship traversal and supports graph-structural analyses including:

- shortest-path and accessibility depth
- door-crossing analysis
- betweenness centrality
- critical route identification
- articulation-point / bottleneck detection

Graph-derived metrics are associated with the relevant spatial entities and incorporated into the retrieved evidence.

## Research Evaluation

The prototype was experimentally evaluated on:

- 28 BIM question-answering queries
- 6 retrieval and reasoning categories
- GPT-4o
- Llama 3.1 70B
- Llama 3.3 70B

The proposed framework was compared with an LLM-first Text-to-Cypher baseline.

### Overall Success Rate

| Model | LLM-first Baseline | Proposed Framework |
|---|---:|---:|
| GPT-4o | 25.00% | 92.86% |
| Llama 3.1 70B | 10.71% | 78.57% |
| Llama 3.3 70B | 7.14% | 78.57% |

The evaluation also considers retrieval quality, latency, token consumption, and observed failure modes.

## Research Focus

This project investigates whether explicit control over the pathway from BIM graph evidence to LLM reasoning can improve the reliability of multi-step BIM question answering.

The broader research focuses on:

- BIM / IFC
- Knowledge Graphs
- GraphRAG
- Context Engineering
- LLM-based reasoning
- Topology-aware BIM retrieval
- Evidence-grounded question answering
