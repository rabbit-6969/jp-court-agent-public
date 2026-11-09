---
inclusion: always
---

# Generation Pipeline Architecture

## Default Mode (Always Active)

```
ES hybrid kNN+BM25 retrieval → Kiro/Claude (inline) → generated output
```

The agent **always uses hybrid search by default** for every retrieval operation.
Documents are retrieved from `case_docs_index` and `statutes_index` using:

- **Vector search (kNN):** 768-dim `all-mpnet-base-v2` embeddings, cosine similarity, boost **0.7**
- **Keyword search (BM25):** full-text match on the `text` field, boost **0.3**
- **num_candidates:** 50 per kNN query
- **top_k:** 10 results by default (1–100 accepted)

Generation is performed directly by Kiro/Claude inline over the retrieved context.

### Why hybrid is the default

Hybrid search provides:
- **Semantic ranking** — surfaces conceptually related rules even when exact terms differ
- **Confidence scores** that reflect legal relevance hierarchy (e.g., §545.062 scored 21.06 vs. next hit at 9.2)
- **Rule tension detection** — returns conflicting sub-chunks of the same rule ranked by relevance to the specific query
- **False-positive suppression** — BM25 matches that are semantically wrong are demoted by the vector component

Validated scores from live case validation:

| Rule | Hybrid Score | Legal Weight |
|---|---|---|
| TTC §545.062 (negligence per se) | 21.06 | Strongest liability anchor |
| TRCP 503.1(b) (appearance bar) | 20.01 | Mandatory default bar |
| TRCP 508.3(e) (post-answer default) | 19.75 | Solid fallback |
| TRCP 503.3 (45-day trial notice) | 14.35 | Procedural timing |
| TRCP 502.7(b) (strike path) | 9.33 | Weak / indirect path |

## BM25-Only Mode (On-Demand)

Use **pure BM25 keyword search** when:

1. The user explicitly requests it: "run keyword search", "BM25 only", "exact term match"
2. The query is a **known exact section reference** (e.g., "find Rule 502.5", "get section 545.062")
3. The embedding model is unavailable or the `hybrid_search.py` script cannot execute
4. The user is debugging retrieval and needs to isolate keyword vs. semantic signal
5. The query contains **highly specific legal citation strings** where BM25 precision is sufficient and semantic drift would hurt

When BM25-only mode is used, note it explicitly in the response:
> `[BM25-only retrieval — semantic ranking not applied]`

## Search Mode Decision Table

| Query type | Default mode | Override to BM25 when |
|---|---|---|
| Legal concept / situation | **Hybrid** | User requests BM25 |
| Document review / analysis | **Hybrid** | — |
| Statute lookup by section number | **Hybrid** | User says "exact match only" |
| Keyword/term audit | BM25 | Always |
| Debugging retrieval pipeline | BM25 | Always |
| User says "hybrid search" | **Hybrid** | — |
| User says "keyword search" / "BM25" | BM25 | Always |

---

## Proposed Feature: ES-Routed Anthropic Generation

**Status:** Proposed — NOT active  
**Feature flag:** `USE_ES_ANTHROPIC_ENDPOINT = false`

### What it would do

Route the retrieved context through the Anthropic Claude inference endpoint
registered in the Elasticsearch cluster, instead of generating inline.

```
ES hybrid kNN+BM25 retrieval → Claude Opus via ES inference endpoint → generated output
```

### ES Inference Endpoint

```json
{
  "inference_id": "anthropic-completion-YOUR-ENDPOINT-ID",
  "task_type": "completion",
  "service": "anthropic",
  "service_settings": {
    "model_id": "claude-opus-4-8",
    "rate_limit": { "requests_per_minute": 50 }
  }
}
```

### How to enable

Call the ES inference API after retrieval:

```python
response = es.inference.inference(
    inference_id='anthropic-completion-YOUR-ENDPOINT-ID',
    body={'input': prompt_with_retrieved_context}
)
```

Where `prompt_with_retrieved_context` is the retrieved documents + task instruction
assembled by the retrieval step.

### Why it's not active

- Adds a second network hop (ES → Anthropic API) per request
- Rate limited to 50 requests/minute on the current endpoint config
- Current inline mode (Kiro/Claude) produces identical output quality since
  both use the same underlying model
- ES inference tool call was blocked in the current execution context

### When to turn it on

- When the agent needs to run **autonomously without Kiro** (e.g. scheduled jobs,
  CLI scripts, or a standalone Python service)
- When you want **full audit trail** of generation calls logged inside ES
- When you want to **swap models** (e.g. switch from Claude Opus to a different
  model) without changing the agent code — just update the ES inference endpoint

### Implementation checklist

- [ ] Set `USE_ES_ANTHROPIC_ENDPOINT = true` in agent config
- [ ] Verify `anthropic-completion-YOUR-ENDPOINT-ID` endpoint is healthy:
  `GET /_inference/anthropic-completion-YOUR-ENDPOINT-ID`
- [ ] Increase rate limit if needed (currently 50 req/min)
- [ ] Test with a single document retrieval + generation call
- [ ] Store generated documents back into `case_docs_index` with
  `type: agent_generated` per the ingestion spec

---

## Project Script Structure

```
jp court agent/
├── core/                          ← core pipeline scripts
│   ├── hybrid_search.py           ← reusable hybrid kNN+BM25 search
│   ├── ingest_doc.py              ← document ingestion (case_docs_index)
│   ├── ingest_statutes_generic.py ← statute ingestion pipeline
│   ├── es_client_utils.py         ← ES client utilities
│   └── get_embedding.py           ← embedding generation tool
└── scripts/                       ← generated/session-specific scripts
    ├── tdi_timeline_search.py
    ├── script_factcheck.py
    ├── release_check.py
    ├── contingency_check.py
    └── ... (all ad-hoc search and analysis scripts)
```

Run core scripts: `python core/hybrid_search.py`
Run session scripts: `python scripts/<name>.py`
