import json
import operator
from typing import Annotated, List, Optional, Dict, TypedDict, Union, Literal
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from config import get_settings
from supabase_client import get_supabase_client

# Load settings
settings = get_settings()
llm = ChatOpenAI(api_key=settings.openai_api_key, model="gpt-4o-mini")

# --- STATE DEFINITION ---
class AgentState(TypedDict):
    """
    Represents the state of the Vectorless Retrieval Workflow.
    """
    query: str
    document_id: Optional[str]
    # List of relevant section headings identified by the Structure Node
    target_sections: List[str]
    # The actual text chunks retrieved from Supabase
    retrieved_chunks: List[Dict]
    # 'yes' or 'no' from the Validation Node
    is_valid: str
    # Final output response
    final_response: Dict
    # Feedback from the Quality Review Node (if any)
    review_feedback: Optional[str]
    # Count of how many times we've tried to improve the answer
    retry_count: int

# --- NODE 1: HIERARCHICAL STRUCTURE NODE ---
def hierarchical_structure_node(state: AgentState):
    print(f"--- NODE 1: HIERARCHICAL STRUCTURE ({state['query']}) ---")
    query = state['query']
    doc_id = state.get('document_id')
    
    sb = get_supabase_client()
    
    # 1. Fetch Document Structure (Table of Contents)
    if not doc_id:
        res = sb.table("documents").select("id").limit(1).execute()
        if res.data:
            doc_id = res.data[0]['id']
        else:
            return {"target_sections": []}

    res = sb.table("chunks").select("section_heading").eq("document_id", doc_id).execute()
    
    if not res.data:
        print("   No structure found.")
        return {"target_sections": []}

    toc = list(set([row['section_heading'] for row in res.data]))
    toc_str = "\n".join([f"- {h}" for h in toc])

    # 2. LLM Reasoning to Select Sections
    system_prompt = """You are a clinical reasoning assistant. 
    You have the Table of Contents (TOC) for a clinical guideline. 
    Identify the specific section headings that are most likely to contain the answer to the user's query.
    Return ONLY a JSON array of strings matching the exact headings from the TOC."""

    user_prompt = f"""Query: {query}
    
    Table of Contents:
    {toc_str}
    
    Return JSON array of relevant headings:"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    response = llm.invoke(messages)
    
    try:
        content = response.content.replace("```json", "").replace("```", "").strip()
        selected_sections = json.loads(content)
        if not isinstance(selected_sections, list):
            selected_sections = []
    except:
        print("   Error parsing LLM response for structure.")
        selected_sections = []

    print(f"   Identified {len(selected_sections)} relevant sections.")
    # Initialize retry_count to 0 here
    return {"target_sections": selected_sections, "document_id": doc_id, "retry_count": 0}


# --- NODE 2: CHUNK RETRIEVAL NODE ---
def chunk_retrieval_node(state: AgentState):
    print("--- NODE 2: CHUNK RETRIEVAL ---")
    sections = state.get("target_sections", [])
    doc_id = state.get("document_id")
    
    if not sections or not doc_id:
        return {"retrieved_chunks": []}
        
    sb = get_supabase_client()
    chunks = []
    
    try:
        res = sb.table("chunks") \
            .select("content, section_heading, id") \
            .eq("document_id", doc_id) \
            .in_("section_heading", sections) \
            .execute()
            
        chunks = res.data if res.data else []
    except Exception as e:
        print(f"   Error fetching chunks: {e}")
        
    print(f"   Retrieved {len(chunks)} chunks.")
    return {"retrieved_chunks": chunks}


# --- NODE 3: VALIDATION NODE ---
def validation_node(state: AgentState):
    print("--- NODE 3: VALIDATION ---")
    query = state['query']
    chunks = state.get('retrieved_chunks', [])
    
    if not chunks:
        return {"is_valid": "no"}

    context_text = "\n\n".join([f"Section: {c['section_heading']}\nContent: {c['content']}" for c in chunks])
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a clinical validator. Determine if the provided context contains sufficient information to answer the query safely."),
        ("human", "Query: {query}\n\nContext:\n{context}\n\nDoes the context contain the answer? Respond with only 'yes' or 'no'.")
    ])
    
    chain = prompt | llm
    response = chain.invoke({"query": query, "context": context_text})
    decision = response.content.strip().lower()
    
    if "yes" in decision:
        decision = "yes"
    else:
        decision = "no"
        
    print(f"   Validation decision: {decision}")
    return {"is_valid": decision}


# --- NODE 4: RESPONSE FORMATTING NODE (Updated for Feedback) ---
def response_formatting_node(state: AgentState):
    print(f"--- NODE 4: RESPONSE FORMATTING (Attempt {state.get('retry_count', 0) + 1}) ---")
    query = state['query']
    chunks = state.get('retrieved_chunks', [])
    feedback = state.get('review_feedback')
    
    context_text = "\n\n".join([f"[Source: {c['section_heading']}] {c['content']}" for c in chunks])
    
    system_prompt = """You are a clinical assistant. Answer the query using ONLY the provided context. 
    Include citations in brackets [Source: Section Name] for every claim.
    Format your response as a JSON object with keys: "answer" and "citations" (list of strings)."""
    
    # Inject feedback if this is a retry
    if feedback:
        system_prompt += f"\n\nIMPORTANT: Your previous attempt was rejected. \nFeedback: {feedback}\nPlease fix these issues in your new response."

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Query: {query}\n\nContext:\n{context_text}")
    ]
    
    response = llm.invoke(messages)
    
    try:
        content = response.content.replace("```json", "").replace("```", "").strip()
        final_json = json.loads(content)
    except:
        final_json = {
            "answer": response.content,
            "citations": []
        }
        
    return {"final_response": final_json}


# --- NODE 5: QUALITY REVIEW NODE (New Function) ---
def quality_review_node(state: AgentState):
    print("--- NODE 5: QUALITY REVIEW ---")
    response = state.get('final_response', {})
    answer_text = response.get('answer', '')
    citations = response.get('citations', [])
    retries = state.get('retry_count', 0)

    # Hard limit on retries to prevent infinite loops
    if retries >= 2:
        print("   Max retries reached. Accepting output.")
        return {"review_feedback": None}

    # LLM grades the output
    system_prompt = """You are a Quality Assurance auditor for a clinical AI. 
    Review the provided answer. It MUST meet these criteria:
    1. It must contain specific citations in the text (e.g., [Source: ...]).
    2. The tone must be professional and clinical.
    3. It must directly answer the user's query.
    
    If it passes, return JSON: {"status": "pass", "feedback": null}
    If it fails, return JSON: {"status": "fail", "feedback": "Specific instructions on what to fix"}
    """
    
    user_content = f"Answer to Audit:\n{answer_text}\n\nCitations listed: {citations}"
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content)
    ]
    
    res = llm.invoke(messages)
    
    try:
        content = res.content.replace("```json", "").replace("```", "").strip()
        grade = json.loads(content)
    except:
        print("   Error parsing grade. Defaulting to pass.")
        return {"review_feedback": None}

    if grade.get("status") == "fail":
        print(f"   Quality Check FAILED: {grade.get('feedback')}")
        return {
            "review_feedback": grade.get("feedback"),
            "retry_count": retries + 1
        }
    else:
        print("   Quality Check PASSED.")
        return {"review_feedback": None}


# --- CONDITIONAL EDGES ---
def decide_next_node(state: AgentState):
    if state["is_valid"] == "yes":
        return "response_formatting"
    else:
        return "insufficient_info"

def check_review_status(state: AgentState):
    """
    If there is feedback, we loop back to formatting.
    If feedback is None, we are done.
    """
    if state.get("review_feedback"):
        return "retry"
    else:
        return "end"

def insufficient_info_node(state: AgentState):
    return {
        "final_response": {
            "answer": "Insufficient information found in the clinical guidelines to answer this query safely.",
            "citations": []
        }
    }

# --- GRAPH CONSTRUCTION ---
def build_graph():
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("hierarchical_structure", hierarchical_structure_node)
    workflow.add_node("chunk_retrieval", chunk_retrieval_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("response_formatting", response_formatting_node)
    workflow.add_node("quality_review", quality_review_node)
    workflow.add_node("insufficient_info", insufficient_info_node)

    # Define Edges
    workflow.set_entry_point("hierarchical_structure")
    
    workflow.add_edge("hierarchical_structure", "chunk_retrieval")
    workflow.add_edge("chunk_retrieval", "validation")
    
    # Conditional Edge 1: Validation -> Formatting OR Insufficient Info
    workflow.add_conditional_edges(
        "validation",
        decide_next_node,
        {
            "response_formatting": "response_formatting",
            "insufficient_info": "insufficient_info"
        }
    )
    
    # Edge: Formatting -> Quality Review
    workflow.add_edge("response_formatting", "quality_review")
    
    # Conditional Edge 2: Quality Review -> Retry Formatting OR End
    workflow.add_conditional_edges(
        "quality_review",
        check_review_status,
        {
            "retry": "response_formatting",
            "end": END
        }
    )
    
    workflow.add_edge("insufficient_info", END)

    return workflow.compile()

# Entry point for usage
app = build_graph()

def run_pipeline(query: str, doc_id: Optional[str] = None):
    """
    Public function to run the vectorless RAG pipeline.
    """
    initial_state = {
        "query": query, 
        "document_id": doc_id, 
        "retry_count": 0,
        "review_feedback": None
    }
    result = app.invoke(initial_state)
    return result.get("final_response")

if __name__ == "__main__":
    # Test run
    test_query = "What is the first line treatment for Type 2 diabetes?"
    print(f"Running pipeline for: {test_query}")
    output = run_pipeline(test_query)
    print("\nFinal Output:")
    print(json.dumps(output, indent=2))