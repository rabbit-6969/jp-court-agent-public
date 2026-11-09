"""
Local script to populate graph edges in case_docs_index.
Utilizes BM25 to fetch documents and JPCourtESClient for local updates.
"""

import os`nimport sys`nsys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))`nfrom es_client_utils import JPCourtESClient
from datetime import datetime

def update_graph_edges(case_id: str):
    client = JPCourtESClient()
    
    # 1. Utilize BM25 to check all case_docs for this Case_ID
    # We use a broad search to retrieve everything linked to the case
    print(f"Fetching all documents for case {case_id}...")
    search_results = client.search(
        index=client.index_name, 
        query_text=None, # Fetch all docs for this Case_ID
        mode="bm25", 
        case_id=case_id, 
        top_k=100
    )
    
    docs = search_results["hits"]["hits"]
    if not docs:
        print("No documents found for this Case_ID.")
        return

    print(f"Analyzing {len(docs)} documents for relationship extraction...")

    # 2. Generate script containing changes adding edges
    # Heuristic logic for building the Legal Knowledge Graph
    for i, current_hit in enumerate(docs):
        current_doc = current_hit["_source"]
        current_id = current_doc["doc_id"]
        current_type = current_doc["type"]
        current_date = datetime.fromisoformat(current_doc["date"].replace('Z', '+00:00'))
        
        new_edges = []

        for other_hit in docs:
            other_doc = other_hit["_source"]
            other_id = other_doc["doc_id"]
            other_type = other_doc["type"]
            other_date = datetime.fromisoformat(other_doc["date"].replace('Z', '+00:00'))

            if current_id == other_id:
                continue

            # Timeline Edges
            if current_date < other_date:
                new_edges.append({"target": other_id, "relation": "timeline_precedes"})
            elif current_date > other_date:
                new_edges.append({"target": other_id, "relation": "timeline_follows"})

            # Evidence & Support Edges (Heuristics)
            # Note: Checking for 'crash report' (space) to handle messy legacy metadata
            if current_type in ["crash_report", "crash report", "estimate", "exhibit"] and other_type == "petition":
                new_edges.append({"target": other_id, "relation": "is_evidence_for"})
            
            if current_type == "analysis" and other_type in ["petition", "complaint"]:
                new_edges.append({"target": other_id, "relation": "supports"})

        # Update the existing document with the new edges
        print(f"Updating {current_id} ({current_type}) with {len(new_edges)} edges...")
        
        # Requirement 2.6: Merge edges to preserve manually added reasoning (supports/contradicts)
        existing_edges = current_doc.get("edges", [])
        seen = {(e["target"], e["relation"]) for e in existing_edges}
        
        for ne in new_edges:
            if (ne["target"], ne["relation"]) not in seen:
                existing_edges.append(ne)

        # Requirement 1.7 & 2.6: Use partial update for existing docs to preserve text and embeddings
        client.es.update(
            index=client.index_name,
            id=current_id,
            body={"doc": {"edges": existing_edges}}
        )

    print("Graph edge generation complete.")

if __name__ == "__main__":
    # Example usage for the current active case
    CASE_ID = os.environ.get("CASE_ID", "YOUR-CASE-ID")
    update_graph_edges(CASE_ID)
