"""
Audit script to identify duplicate documents in case_docs_index.
Checks for duplicate doc_ids, titles, and overlapping text content.
"""

from es_client_utils import JPCourtESClient
from collections import Counter

def audit_duplicates():
    client = JPCourtESClient()
    # Retrieve all documents (up to 100 for this case)
    res = client.es.search(index=client.index_name, size=100, query={"match_all": {}}, sort=[{"type": "asc"}, {"date": "desc"}])
    hits = res["hits"]["hits"]
    
    print(f"Total documents in {client.index_name}: {len(hits)}")
    
    titles = []
    doc_ids = []
    content_hashes = []
    
    for hit in hits:
        source = hit["_source"]
        es_id = hit["_id"]
        doc_id = source.get("doc_id")
        title = source.get("title", "Untitled")
        text = source.get("text", "")
        
        titles.append(title)
        doc_ids.append(doc_id)
        # Use a simple snippet as a proxy for content duplication
        content_hashes.append(text[:200] if text else "")

    # 1. Check for doc_id field duplication (where _id != doc_id)
    id_counts = Counter(doc_ids)
    duplicate_ids = {k: v for k, v in id_counts.items() if v > 1}
    
    # 2. Check for Title duplication
    title_counts = Counter(titles)
    duplicate_titles = {k: v for k, v in title_counts.items() if v > 1}

    # 3. Check for Content duplication
    content_counts = Counter(content_hashes)
    duplicate_content = {k: v for k, v in content_counts.items() if v > 1 and k != ""}

    print("\n" + "="*80)
    print(f"{'TYPE':<20} | {'DOC_ID':<25} | {'TITLE'}")
    print("-" * 80)
    for hit in hits:
        s = hit["_source"]
        print(f"{str(s.get('type')):<20} | {str(s.get('doc_id')):<25} | {s.get('title', 'Untitled')}")
    print("="*80)

    print("\n--- Duplicate Summary ---")
    print(f"Duplicate 'doc_id' fields: {duplicate_ids if duplicate_ids else 'None'}")
    print(f"Duplicate 'title' fields:  {duplicate_titles if duplicate_titles else 'None'}")
    print(f"Near-Duplicate Content:   {len(duplicate_content)} groups found")

if __name__ == "__main__":
    audit_duplicates()
