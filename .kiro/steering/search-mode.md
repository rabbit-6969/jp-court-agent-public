---
inclusion: always
---

# Search Mode Selection Rules

## Default: Always Hybrid

The agent uses **hybrid kNN+BM25 search** for every retrieval operation by default.

```
Model:        all-mpnet-base-v2
Dimensions:   768
kNN boost:    0.7  (cosine similarity)
BM25 boost:   0.3  (keyword match)
num_candidates: 50
top_k:        10   (default, range 1–100)
Indexes:      case_docs_index, statutes_index
```

Always label hybrid results:
> `[Hybrid kNN+BM25 — all-mpnet-base-v2 768-dim, 0.7 cosine / 0.3 BM25]`

## When to Switch to BM25-Only

Switch to **pure BM25 keyword search** (no embedding generated) when ANY of these conditions are true:

| Trigger | Example user phrase |
|---|---|
| User explicitly requests BM25 | "keyword search", "BM25 only", "exact match", "exact term", "run BM25" |
| User wants keyword-only | "keyword only", "no semantic", "just keywords" |
| Verbatim section/rule lookup with no interpretation needed | "get Rule 502.5 text", "show me section 545.062 verbatim" |
| Debugging retrieval pipeline | "compare BM25 vs hybrid", "test keyword retrieval" |
| Embedding model unavailable | Auto-fallback, log warning |

Always label BM25-only results:
> `[BM25-only retrieval — semantic ranking not applied]`

## Why Hybrid is Superior for Legal Retrieval

From live validation on case *********** (12 queries, all-mpnet-base-v2):

| Capability | BM25 | Hybrid |
|---|---|---|
| Exact legal term matching | ✅ | ✅ |
| Semantic / paraphrase matching | ❌ | ✅ |
| Rule hierarchy via confidence scores | ❌ | ✅ |
| Intra-rule conflict detection (different sub-chunks) | ❌ | ✅ |
| False-positive suppression | ❌ | ✅ |
| Procedural path mapping | ❌ | ✅ |

Key validated scores:
- **§545.062 (negligence per se):** 21.06 — highest in run
- **TRCP 503.1(b) (appearance bar):** 20.01
- **TRCP 508.3(e) (post-answer default):** 19.75
- **TRCP 502.7(b) (strike path):** 9.33 — correctly ranked weak

BM25 retrieved the same rules but could not produce this confidence hierarchy.

## Response Annotation Format

Every retrieval response must include a header line:

For hybrid:
```
[Hybrid kNN+BM25 — all-mpnet-base-v2 768-dim, 0.7 cosine / 0.3 BM25]
```

For BM25:
```
[BM25-only retrieval — semantic ranking not applied]
```

For auto-fallback:
```
[BM25 fallback — Embedding_Tool unavailable, hybrid not executed]
```

## Python Execution

**Project structure:**
- `core/hybrid_search.py` — core reusable hybrid search script
- `core/ingest_doc.py` — document ingestion (case_docs_index)
- `core/ingest_statutes_generic.py` — statute ingestion pipeline
- `core/es_client_utils.py` — ES client utilities
- `core/get_embedding.py` — embedding generation tool
- `scripts/` — all generated/session-specific scripts

Run core scripts from the project root: `python core/hybrid_search.py`
Run session scripts from the project root: `python scripts/<name>.py`

When running true hybrid search via script, use `core/hybrid_search.py`:

```python
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch

ES_API_KEY = "your-elasticsearch-api-key-here"
model = SentenceTransformer("all-mpnet-base-v2")  # 768-dim
es = Elasticsearch("http://localhost:9200", api_key=ES_API_KEY)

def hybrid_search(index, query_text, case_id_filter=None, k=10):
    vec = model.encode(query_text).tolist()
    body = {
        "size": k,
        "knn": {
            "field": "embedding",
            "query_vector": vec,
            "k": k,
            "num_candidates": 50,
            "boost": 0.7,
            **({"filter": {"term": {"case_id": case_id_filter}}} if case_id_filter else {})
        },
        "query": {
            "bool": {
                "must": [{"match": {"text": {"query": query_text, "boost": 0.3}}}],
                **({"filter": [{"term": {"case_id": case_id_filter}}]} if case_id_filter else {})
            }
        }
    }
    return es.search(index=index, body=body)["hits"]["hits"]
```

When running via MCP ES tool (no embedding support), use BM25 and annotate accordingly.
