"""
Retrieves existing documents from ES to verify field content 
against Exhibit C and Timeline references.
"""

from es_client_utils import JPCourtESClient
import json
import re

def analyze_case_state(case_id: str):
    client = JPCourtESClient()
    
    # We use BM25 to get a comprehensive list of what is already indexed
    print(f"Retrieving existing documents for Case: {case_id}...")
    results = client.search(
        index=client.index_name,
        query_text=None, # Broad retrieval
        mode="bm25",
        case_id=case_id,
        top_k=50
    )
    
    raw_hits = results["hits"]["hits"]
    if not raw_hits:
        print("No documents found in ES for this case.")
        return

    # De-duplicate results by doc_id to ensure the output is high-signal
    hits = []
    seen_ids = set()
    for hit in raw_hits:
        did = hit["_source"].get("doc_id")
        if did and did not in seen_ids:
            seen_ids.add(did)
            hits.append(hit)

    print(f"\n--- Found {len(hits)} unique documents. Analysis of fields: ---\n")
    
    for hit in hits:
        doc = hit["_source"]
        print(f"ID: {doc['doc_id']}")
        print(f"Type: {doc['type']}")
        print(f"Title: {doc['title']}")
        print(f"Date: {doc['date']}")
        
        # Clearer edge reporting
        edges = doc.get('edges', [])
        print(f"Edges ({len(edges)}):")
        for edge in edges:
            print(f"  - [{edge['relation']}] -> {edge['target']}")
        
        # Debugging Section: Inspecting specific text for "Residence" verification
        raw_text = doc.get('text', '')
        text_upper = raw_text.upper()
        
        if doc['doc_id'] == "DOC-12F199F8":
            print("  [DEBUG] Inspecting Insurance Estimate text for verification string...")
            # Improved verification logic using regex
            match = re.search(r"(.{0,40})RESIDENCE(.{0,60})", raw_text, re.IGNORECASE | re.DOTALL)
            if match:
                context = match.group(0).replace('\n', ' ')
                print(f"  [DEBUG] Found 'RESIDENCE'. Context: \"...{context}...\"")

        if doc['doc_id'] == "DOC-12F199F8":
             print("  [DEBUG] Inspecting Estimate for unreliability markers...")
             if "RESIDENCE" in text_upper:
                 print("  [ALERT] Estimate claims RESIDENCE inspection. Shop data contradicts this.")
             if "$701" in text_upper:
                 print(f"  [ALERT] Estimate amount ($701.64) is 31% of shop teardown ($2,241.43).")
             if "TEARDOWN" not in text_upper:
                 print("  [ALERT] No 'TEARDOWN' mentioned in insurer estimate. Shop performed full teardown.")

        if doc['doc_id'] == "DOC-5C6E8A35":
            print("  [DEBUG] Inspecting Insurance Check text for settlement language...")
            # Keywords for accord and satisfaction
            match = re.search(r"(.{0,40})(FULL|FINAL|SETTLEMENT|SATISFACTION|RELEASE)(.{0,40})", raw_text, re.IGNORECASE | re.DOTALL)
            if match:
                print(f"  [DEBUG] ALERT: Found potential settlement language. Context: \"...{match.group(0).replace('\n', ' ')}...\"")

        if "INSPECTION" in text_upper: print("-> Found Inspection-related text.")
        if "DEFAULT" in text_upper:    print("-> Found Default-related text.")

        # Requirement 4.4: Show text for agent-generated documents
        if doc.get('type') == "agent_generated" or "agent_generated" in doc.get('tags', []):
            print(f"\n--- AGENT CONTENT ---\n{raw_text}\n--- END CONTENT ---\n")
            
        print("-" * 40)

if __name__ == "__main__":
    CASE_ID = "YOUR-CASE-ID"
    analyze_case_state(CASE_ID)
