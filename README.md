# context-engineering-graphrag-bim
Research prototype for reliable LLM-based reasoning over IFC-derived BIM knowledge graphs using Context Engineering and GraphRAG.

## Key Components

### 1. IFC Processing

The BIM model is processed using IfcOpenShell. The preprocessing stage extracts relevant IFC entities, semantic attributes, geometric descriptors, quantitative information, materials, property sets, type definitions, and native IFC relationships.

Dimensional and quantitative values are normalized according to the IFC project unit context before graph materialization.

### 2. BIM Knowledge Graph

The extracted BIM information is materialized as a Neo4j Property Graph. IFC entities become graph nodes and normalized relationships become typed graph edges.

### 3. Spatial Accessibility Enrichment

Because native IFC relationships do not explicitly encode all navigable spatial relationships, additional accessibility relations are derived from the geometric configuration of spaces and their surrounding walls, doors, and openings.

The enrichment layer introduces:

- `OPEN_ACCESS`
- `ACCESS_BY_DOOR`
- `ADJACENT_WALL`

These relations provide an explicit spatial connectivity layer for topology-aware retrieval and graph analysis.

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

### 5. IFC Schema Alignment

Architectural concepts extracted from the query are aligned with IFC entity classes using a local ChromaDB knowledge base containing IFC classes, semantic descriptions, and architectural synonyms.

Semantic similarity retrieval is combined with lexical consistency filtering and fallback handling to reduce schema-mapping ambiguity.

### 6. Query-Specific Graph Retrieval

The structured retrieval requirements are translated into dynamically assembled Cypher operations rather than relying on a fixed graph query.

The retrieval layer supports:

- spatial containment and boundary retrieval
- property and quantity filtering
- material and layer retrieval
- accessibility analysis
- shortest-path routing
- global accessibility analysis
- betweenness centrality
- critical-route analysis
- bottleneck / articulation-point analysis

Numerical and material constraints can be evaluated against retrieved BIM evidence after graph traversal.

### 7. Evidence Consolidation and Context Assembly

Retrieved graph evidence is not passed directly to the language model. Instead, the evidence is processed through query-specific validation, consolidation and integration, and context assembly.

This stage verifies attribute-level, numerical, and material constraints, removes redundant or overlapping representations, and integrates complementary evidence associated with the same BIM entities and spatial contexts.

The retained evidence is then normalized into a structured, query-specific context containing the entity, spatial, property, material, and topology information required for grounded LLM reasoning.

### 8. Evidence-Oriented LLM Interaction

The BIM query interface is exposed to the language model as a tool, separating structured BIM retrieval from final language-model reasoning.

The current prototype uses a LangGraph ReAct-style agent with the BIM query tool. Tool calls, arguments, retrieved graph outputs, and token usage are logged during execution for experimental analysis.

## Example Query

**User query**

> Find walls in the living room with insulation thicker than 5 cm.

**Structured query**

```json
{
  "element_type": "Wall",
  "reference_space_name": "Living Room",
  "material_filter": "insulation",
  "fetch_materials": true,
  "condition": "thickness > 0.05"
}
```
