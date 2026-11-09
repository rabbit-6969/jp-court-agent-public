# JP Court Agent

An AI-powered legal case management agent using Elasticsearch as its persistent knowledge base.

The agent ingests, stores, and retrieves legal case documents using hybrid kNN+BM25 search
(all-mpnet-base-v2, 768-dim, 0.7 cosine / 0.3 BM25), generates new analysis documents,
and stores them back into Elasticsearch - creating a self-improving reasoning loop.

## Architecture

```
ES hybrid kNN+BM25 retrieval (all-mpnet-base-v2 768-dim)
    |
    v
Kiro/Claude inline reasoning over retrieved context
    |
    v
Generated documents stored back to case_docs_index
```

## Stack

- **Elasticsearch** - document store with dense vector (kNN) support
- **SentenceTransformers** - `all-mpnet-base-v2` for 768-dim embeddings
- **Python** - `elasticsearch`, `sentence-transformers`, `pypdf`, `tqdm`
- **Kiro** - AI agent IDE (generation pipeline)

## Elasticsearch Indexes

| Index | Purpose |
|---|---|
| `case_docs_index` | All case documents (crash reports, petitions, estimates, emails, exhibits, agent-generated) |
| `statutes_index` | Texas statutes and rules of civil procedure (chunked, embedded) |

## Setup

1. **Install dependencies**
   ```bash
   pip install elasticsearch sentence-transformers pypdf tqdm python-dotenv
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env and fill in ES_HOST, ES_API_KEY, CASE_ID
   ```

3. **Start Elasticsearch** (local or cloud)

4. **Ingest statutes** (optional - for legal research queries)
   ```bash
   python core/ingest_statutes_generic.py \
     --pdf "path/to/texas-rules-of-civil-procedure.pdf" \
     --title "Texas Rules of Civil Procedure" \
     --pattern trcp \
     --ingest
   ```

5. **Ingest case documents**
   ```bash
   python core/ingest_doc.py
   ```

6. **Run hybrid search**
   ```bash
   export ES_API_KEY="your-key"
   export CASE_ID="YOUR-CASE-ID"
   python core/hybrid_search.py
   ```

## Project Structure

```
jp-court-agent/
|-- core/                          # Core pipeline scripts
|   |-- es_client_utils.py         # ES client with hybrid search, graph traversal, ingestion
|   |-- hybrid_search.py           # Standalone hybrid kNN+BM25 search runner
|   |-- ingest_doc.py              # Interactive document ingestion tool
|   |-- ingest_statutes_generic.py # PDF statute extraction + ingestion pipeline
|   +-- get_embedding.py           # Standalone embedding generation utility
|-- scripts/                       # Agent session scripts (analysis, enforcement, etc.)
|-- .kiro/
|   |-- specs/jp-court-agent/
|   |   +-- requirements.md        # Full system requirements
|   +-- steering/
|       |-- generation-pipeline.md # Pipeline architecture rules
|       +-- search-mode.md         # Hybrid vs BM25 selection rules
|-- .env.example                   # Environment variable template
+-- README.md
```

## Document Schema

```json
{
  "doc_id":    "DOC-XXXXXXXX",
  "case_id":   "YOUR-CASE-ID",
  "type":      "petition|estimate|email|exhibit|agent_generated|...",
  "title":     "Document title",
  "text":      "Full document text",
  "date":      "YYYY-MM-DD",
  "tags":      ["tag1", "tag2"],
  "embedding": [0.123, "...768 dims"],
  "edges":     [{"target": "DOC-YYYYYYYY", "relation": "supports"}]
}
```

## Search Modes

| Mode | When to use |
|---|---|
| `hybrid` (default) | All analytical queries - combines semantic + keyword |
| `bm25` | Exact section/citation lookup or user requests keyword search |
| `graph` | Multi-hop reasoning across document relationships |

## License

MIT