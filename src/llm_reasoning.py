import os
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from .graph_retrieval import execute_master_bim_query

PROXY_URL = os.getenv("PROXY_URL", "")

graph = Neo4jGraph(URL,USERNAME,PASSWORD)

tools = [execute_master_bim_query]

system_prompt = """
    You are an expert Building Information Modeling (BIM) assistant.
    Your job is to answer user queries accurately based on the data retrieved from the BIM database.
    
    Follow these guidelines:
    
    1. GENERAL ARCHITECTURAL & TOPOLOGICAL ANALYSIS:
       - If the user asks for general topological analysis or privacy principles, use `element_type='space'` and `topology_relation='SHORTEST_PATH'`.
       - Base explanations of spatial metrics strictly on relative standings in the dataset without speculation.

    2. PROPERTY & MATERIAL PRIORITY:
       - Extract mentioned metric names (e.g., 'Area', 'Volume') into the `properties` array.
       - For material layer thickness, set `fetch_materials=True`.

    3. DATA REPORTING & CONCISENESS (OPTIMIZED):
       - Present retrieved data clearly and factually.
       - You may aggregate total values (e.g., total area) while providing a concise structural breakdown of the spaces.
       - Strictly cross-reference entities with user requests.
       - FACT-PRESERVING SYNTHESIS & METRIC FIDELITY:
          When categorizing or grouping entities into higher-level analytical themes (e.g., by access level, spatial depth, structural capacity, size, or material performance), ensure that quantitative and topological metrics attributed to grouped items remain strictly accurate. 
          * NEVER merge entities under a single numeric metric if their actual values differ in the tool output (e.g., do not group 2-step and 3-step paths under "3 steps", nor group 200mm and 300mm elements under a single thickness).
          * Explicitly distinguish varying values within your narrative (e.g., "reaches the Foyer at 2 steps and Living Room at 3 steps", or "varies from 200mm in interior walls to 300mm in exterior walls").
          * Retain full autonomy to synthesize broader architectural/engineering patterns and trends, provided that the underlying values for individual entities remain factually uncompromised.
            
    4. STRICT METRIC USAGE (NO HALLUCINATION):
       - NEVER use terms like "Mean Topological Depth (MTD)", "Betweenness", or "Integration" unless the tool explicitly returns these exact global metrics. 
       - If the tool only returns local path evidence (e.g., "Total Depth: 1 steps", "Doors to cross: 1"), limit your interpretation to local connectivity, direct/indirect access, and physical barriers.
    
    5. EXTERNAL SYNTHESIS & INDEPENDENT REASONING (HYBRID ANALYSIS):
       - If a query requires comparing the retrieved BIM data to ANY external reference, historical precedent, theoretical framework, or specific standard (e.g., a specific building, infrastructure, or concept) NOT explicitly present in the tool's output:
         * AVOID acting as a mere data reporter. Do not just list or dump metrics.
         * SYNTHESIS OVER STRUCTURE: Do not use rigid formats like "Step 1, Step 2" or mechanical bullet points. Weave your analysis into a cohesive, natural, and highly analytical expert narrative.
         * DATA GROUNDING: Deduce the current model's behavior strictly from the retrieved graph metrics (e.g., connectivity, depth, bottlenecks).
         * PARAMETRIC KNOWLEDGE: Actively and independently leverage your pre-trained knowledge to explain the rules, hierarchy, or characteristics of the requested external reference.
         * CRITICAL COMPARISON: Critically and deeply evaluate how the graph-derived metrics of the current model align, contrast, or conform with your theoretical knowledge of the external reference.
         * TRANSPARENCY: Naturally distinguish in your phrasing between what the BIM data reveals about the current model, and what your engineering/architectural knowledge dictates about the external reference.
    """

agent_executor = create_react_agent(llm, tools, prompt=system_prompt)

total_input_tokens = 0
total_output_tokens = 0
total_combined_tokens = 0

sample_question = "Q27. Explain the structural role of the hallway in the spatial accessibility network using shortest-path evidence?"

inputs = {"messages": [("user", sample_question)]} 

final_response = ""

for step in agent_executor.stream(inputs, stream_mode="updates"):
    for node_name, node_state in step.items():
        if "messages" in node_state:
            last_msg = node_state["messages"][-1]
            
            if last_msg.type == 'ai':
                if hasattr(last_msg, 'usage_metadata') and last_msg.usage_metadata:
                    usage = last_msg.usage_metadata
                    total_input_tokens += usage.get("input_tokens", 0)
                    total_output_tokens += usage.get("output_tokens", 0)
                    total_combined_tokens += usage.get("total_tokens", 0)
                elif hasattr(last_msg, 'response_metadata') and 'token_usage' in last_msg.response_metadata:
                    usage = last_msg.response_metadata['token_usage']
                    total_input_tokens += usage.get("prompt_tokens", 0)
                    total_output_tokens += usage.get("completion_tokens", 0)
                    total_combined_tokens += usage.get("total_tokens", 0)

            if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                print(f" [LLM DECISION] Calling Tool: {last_msg.tool_calls[0]['name']}")
                print(f"[TOOL ARGUMENTS]: {last_msg.tool_calls[0]['args']}")
                print("-" * 50)
            
            elif last_msg.type == 'tool':
                print(f" [TOOL OUTPUT] (Truncated for logs):")
                print(last_msg.content[:10000] + " .\n[Output Truncated]")
                print("-" * 50)
            
            elif last_msg.type == 'ai' and last_msg.content:
                final_response = last_msg.content
                
print(f"\n AI Final Answer:\n{final_response}")

print("=" * 50)
print(" TOKEN CONSUMPTION REPORT ")
print(f"Total Input (Prompt) Tokens:  {total_input_tokens:,}")
print(f"Total Output (Completion) Tokens: {total_output_tokens:,}")
print(f" TOTAL CONSUMED TOKENS (For this Question): {total_combined_tokens:,}")
print("=" * 50)
