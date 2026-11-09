import os
"""
True hybrid kNN + BM25 search against case_docs_index and statutes_index.
Mirrors ingest_doc.py: all-mpnet-base-v2, 768-dim embeddings.
Weights: 0.7 cosine (knn) / 0.3 BM25 (match) per generation-pipeline.md
"""

from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch
import json

# --- Config ---
ES_HOST    = "http://localhost:9200"
ES_API_KEY = os.environ.get("ES_API_KEY", "")
CASE_INDEX = "case_docs_index"
STATUTES_INDEX = "statutes_index"
CASE_ID = os.environ.get("CASE_ID", "YOUR-CASE-ID")
KNN_BOOST = 0.7
BM25_BOOST = 0.3
TOP_K = 10

# --- Load model (same as ingest_doc.py) ---
print("Loading all-mpnet-base-v2...")
model = SentenceTransformer("all-mpnet-base-v2")
es = Elasticsearch(ES_HOST, api_key=ES_API_KEY)

def embed(text: str) -> list:
    return model.encode(text).tolist()

def hybrid_search(index: str, query_text: str, extra_filter: dict = None, k: int = TOP_K) -> list:
    """Run true hybrid kNN + BM25 query."""
    vec = embed(query_text)

    body = {
        "size": k,
        "_source": ["doc_id", "case_id", "type", "title", "text", "date", "section", "heading", "tags"],
        "highlight": {"fields": {"text": {"fragment_size": 400, "number_of_fragments": 2}}},
        "knn": {
            "field": "embedding",
            "query_vector": vec,
            "k": k,
            "num_candidates": 50,
            "boost": KNN_BOOST,
            **({"filter": extra_filter} if extra_filter else {})
        },
        "query": {
            "bool": {
                "must": [{"match": {"text": {"query": query_text, "boost": BM25_BOOST}}}],
                **({"filter": [extra_filter]} if extra_filter else {})
            }
        }
    }
    resp = es.search(index=index, body=body)
    return resp["hits"]["hits"]

def print_results(label: str, hits: list):
    print(f"\n{'='*70}")
    print(f"QUERY: {label}")
    print(f"{'='*70}")
    for i, h in enumerate(hits, 1):
        s = h["_source"]
        score = round(h["_score"], 4)
        title = s.get("title") or s.get("heading") or s.get("section", "")
        section = s.get("section", "")
        doc_id = s.get("doc_id", "")
        snippet = ""
        if "highlight" in h:
            snippet = " ... ".join(h["highlight"].get("text", []))[:300]
        else:
            snippet = s.get("text", "")[:300]
        print(f"\n[{i}] score={score} | {doc_id or section} | {title}")
        print(f"    {snippet}")

# ── QUERIES ──────────────────────────────────────────────────────────────────

CASE_FILTER = {"term": {"case_id": CASE_ID}}

queries = [
    # Q1 — Core: late answer before default judgment signed
    ("statutes_index", "late untimely answer filed after deadline no leave court default judgment still barred appearance before signed", None),
    # Q2 — TRCP 503.1 mandatory bar
    ("statutes_index", "defendant files answer before default judgment signed judge must not enter default judgment case set for trial", None),
    # Q3 — Strike pleading late filing insufficient justice court 502.7
    ("statutes_index", "strike pleading answer untimely late filed court order insufficient amend fail comply 502.7", None),
    # Q4 — Default judgment proof damages hearing other cases plaintiff appear
    ("statutes_index", "default judgment other cases plaintiff request hearing appear prove damages evidence", None),
    # Q5 — Post-answer default defendant fails appear trial liability
    ("statutes_index", "post answer default defendant answered fails appear trial court hear evidence liability damages judgment", None),
    # Q6 — General denial sufficient appearance does not bar defense
    ("statutes_index", "general denial sufficient constitute answer appearance does not bar defendant raising defense trial 502.5", None),
    # Q7 — 502.5 answer due date 14 days service citation
    ("statutes_index", "answer due date 14 days after service citation defendant justice court 502.5", None),
    # Q8 — 503.3 trial setting notice 45 days after defendant answers
    ("statutes_index", "after defendant answers case set trial docket court send notice 45 days 503.3", None),
    # Q9 — Case docs: answer timeline default motion
    ("case_docs_index", "defendant answer late May 21 deadline June 1 default judgment motion strike", CASE_FILTER),
    # Q10 — Case docs: liability negligence per se crash rear end
    ("case_docs_index", "rear end collision followed too closely negligence per se police report contributing factor", CASE_FILTER),
    # Q11 — Statutes: negligence per se 545.062 following distance assured clear
    ("statutes_index", "operator following vehicle maintain assured clear distance stop without colliding preceding vehicle 545.062", None),
    # Q12 — Statutes: 505.3 motion set aside default judgment 14 days good cause
    ("statutes_index", "motion set aside default judgment 14 days good cause signed 505.3", None),
]

print("\n\n=== TRUE HYBRID kNN+BM25 SEARCH — all-mpnet-base-v2 768-dim ===")
print(f"=== Case: {CASE_ID} | kNN boost={KNN_BOOST} | BM25 boost={BM25_BOOST} ===\n")

results = {}
for (index, query, filt) in queries:
    try:
        hits = hybrid_search(index, query, extra_filter=filt, k=5)
        results[query[:60]] = hits
        print_results(f"[{index}] {query[:80]}", hits)
    except Exception as e:
        print(f"\nERROR on query '{query[:60]}': {e}")

print("\n\n=== SEARCH COMPLETE ===")
