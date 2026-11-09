"""
Utility to normalize document types (e.g., 'crash report' -> 'crash_report')
to ensure compliance with requirements.md.
"""

from es_client_utils import JPCourtESClient

def normalize():
    client = JPCourtESClient()
    # Broad search for the case
    res = client.es.search(index=client.index_name, size=100, query={"match_all": {}})
    hits = res["hits"]["hits"]
    
    updates = {
        "crash report": "crash_report"
    }
    
    print("Checking for metadata normalization...")
    for hit in hits:
        doc_id = hit["_id"]
        doc_type = hit["_source"].get("type")
        
        if doc_type in updates:
            new_type = updates[doc_type]
            print(f"  Fixing {doc_id}: '{doc_type}' -> '{new_type}'")
            client.es.update(index=client.index_name, id=doc_id, body={"doc": {"type": new_type}})
    
    print("Done.")

if __name__ == "__main__":
    normalize()
