import os
"""
Core Elasticsearch client utilities for JP Court Agent.
Encapsulates local embedding generation (all-mpnet-base-v2) and 
hybrid kNN + BM25 search logic.
"""

from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch
import re
import json

class JPCourtESClient:
    VALID_TYPES = [
        "crash_report", "estimate", "petition", "complaint", "email", "letter",
        "timeline", "discrepancy_report", "exhibit", "summary", "analysis",
        "insurer_response", "tdi_response", "agent_generated"
    ]

    VALID_RELATIONS = [
        "supports", "contradicts", "timeline_precedes", "timeline_follows",
        "is_evidence_for", "is_related_to"
    ]

    def __init__(self, es_host="http://localhost:9200", api_key=None, debug=True):
        self.es_host = es_host
        self.api_key = api_key or os.environ.get("ES_API_KEY", "")
        self.index_name = "case_docs_index"
        self.debug = debug
        print("Loading local model all-mpnet-base-v2...")
        self.model = SentenceTransformer("all-mpnet-base-v2")
        self.es = Elasticsearch(self.es_host, api_key=self.api_key)

    def _log_query(self, mode: str, body: dict):
        """Requirement 8.10: Print explanation of query DSL."""
        if self.debug:
            try:
                # Deep copy via JSON to avoid modifying the original query object
                log_body = json.loads(json.dumps(body))
                
                # Truncate large vectors for readability in debug output
                if "knn" in log_body and isinstance(log_body["knn"], dict):
                    if "query_vector" in log_body["knn"]:
                        vec = log_body["knn"]["query_vector"]
                        log_body["knn"]["query_vector"] = vec[:3] + [f"... ({len(vec)} dims)"]

                if "embedding" in log_body and isinstance(log_body["embedding"], list):
                    vec = log_body["embedding"]
                    log_body["embedding"] = vec[:3] + [f"... ({len(vec)} dims)"]

                print(f"\n[DEBUG-ES] Mode: {mode.upper()}")
                print(f"[DEBUG-ES] Request Body:\n{json.dumps(log_body, indent=2)}")
                print("[DEBUG-ES] Request execution complete.")
            except Exception as e:
                print(f"\n[DEBUG-ES] (Failed to log debug body: {e})")

    def embed(self, text: str) -> list:
        """Generate 768-dim embedding locally."""
        if not text.strip():
            raise ValueError("Input text cannot be empty.")
        return self.model.encode(text).tolist()

    def validate_case_id(self, case_id: str):
        """Requirement 6.4: Validate Case_ID format (1-64 chars, alphanumeric/hyphens/underscores)."""
        if not isinstance(case_id, str) or not (1 <= len(case_id) <= 64):
            raise ValueError("Case_ID must be a string between 1 and 64 characters.")
        if not re.match(r"^[a-zA-Z0-9\-_]+$", case_id):
            raise ValueError("Case_ID contains invalid characters.")

    def ingest_document(self, doc_id: str, case_id: str, doc_type: str, title: str, text: str, date: str, tags: list, edges: list = None):
        """Ingest a document with local embedding generation."""
        # Requirement 6.4
        self.validate_case_id(case_id)

        # Requirement 1.7: Reject if doc_id already exists
        if self.es.exists(index=self.index_name, id=doc_id):
            raise ValueError(f"Requirement 1.7 Violation: doc_id '{doc_id}' already exists.")

        # Requirement 1.1 & 1.4: Validate type
        if doc_type not in self.VALID_TYPES:
            raise ValueError(f"Requirement 1.4 Violation: Invalid type '{doc_type}'")

        # Requirement 1.2: Ensure required fields are non-empty
        fields = {"doc_id": doc_id, "case_id": case_id, "type": doc_type, "title": title, "text": text, "date": date, "tags": tags}
        for field, value in fields.items():
            if value is None or (hasattr(value, "__len__") and len(value) == 0):
                raise ValueError(f"Requirement 1.2 Violation: Field '{field}' cannot be empty.")

        # Requirement 1.3: Validate Relation_Types
        edges = edges or []
        for edge in edges:
            if edge.get("relation") not in self.VALID_RELATIONS:
                raise ValueError(f"Requirement 1.4 Violation: Invalid Relation_Type '{edge.get('relation')}'")

        embedding = self.embed(text)
        document = {
            "doc_id": doc_id,
            "case_id": case_id,
            "type": doc_type,
            "title": title,
            "text": text,
            "date": date,
            "tags": tags,
            "embedding": embedding,
            "edges": edges or []
        }
        res = self.es.index(index=self.index_name, id=doc_id, document=document)
        self._log_query("ingest", document)
        return res

    def search(self, index: str, query_text: str, mode: str = "hybrid", case_id: str = None, top_k=10):
        """
        Execute search based on search-mode.md rules.
        Default is hybrid.
        """
        if mode == "hybrid":
            try:
                return self.hybrid_search(index, query_text, case_id, top_k)
            except Exception as e:
                print(f"Hybrid search failed, falling back to BM25: {e}")
                return self.bm25_search(index, query_text, case_id, top_k)
        elif mode == "graph":
            return self.graph_search(index, query_text, case_id, top_k)
        else:
            return self.bm25_search(index, query_text, case_id, top_k)

    def graph_search(self, index: str, query_text: str, case_id: str = None, top_k=5):
        """
        1. Get hybrid seeds.
        2. Traverse edges to get neighbors.
        3. Return merged de-duplicated set.
        """
        # Step 1: Hybrid Seeds
        seeds = self.hybrid_search(index, query_text, case_id, top_k=top_k)
        seed_hits = seeds["hits"]["hits"]
        
        # Step 2: Collect target IDs from edges
        target_ids = set()
        for hit in seed_hits:
            edges = hit["_source"].get("edges", [])
            for edge in edges:
                target_ids.add(edge["target"])
        
        if not target_ids:
            return seeds

        # Step 3: Fetch Neighbors
        neighbor_query = {
            "query": {
                "bool": {
                    "must": [{"ids": {"values": list(target_ids)}}],
                    "filter": [{"term": {"case_id": case_id}}] if case_id else []
                }
            }
        }
        neighbors = self.es.search(index=index, body=neighbor_query)
        self._log_query("graph_neighbors", neighbor_query)
        
        # Step 4: Merge (Simplistic merge for this utility)
        all_hits = {hit["_id"]: hit for hit in seed_hits}
        for hit in neighbors["hits"]["hits"]:
            all_hits[hit["_id"]] = hit
            
        seeds["hits"]["hits"] = list(all_hits.values())
        seeds["hits"]["total"]["value"] = len(seeds["hits"]["hits"])
        return seeds
    def bm25_search(self, index: str, query_text: str, case_id: str = None, top_k=10):
        """Execute pure BM25 keyword search with optional case isolation."""
        case_filter = {"term": {"case_id": case_id}} if case_id else None
        
        # Requirement: If query_text is empty, return all docs matching the filter
        must_clause = {"match": {"text": {"query": query_text}}} if query_text else {"match_all": {}}

        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [must_clause],
                    **({"filter": [case_filter]} if case_filter else {})
                }
            },
            "highlight": {
                "fields": {"text": {"fragment_size": 400, "number_of_fragments": 2}}
            }
        }
        res = self.es.search(index=index, body=body)
        self._log_query("bm25", body)
        return res

    def hybrid_search(self, index: str, query_text: str, case_id: str = None, top_k=10, knn_boost=0.7, bm25_boost=0.3):
        """Execute true hybrid kNN + BM25 search with optional case isolation."""
        query_vec = self.embed(query_text)
        
        # Optional case isolation filter
        case_filter = {"term": {"case_id": case_id}} if case_id else None

        body = {
            "size": top_k,
            "knn": {
                "field": "embedding",
                "query_vector": query_vec,
                "k": top_k,
                "num_candidates": 50,
                "boost": knn_boost,
                **({"filter": case_filter} if case_filter else {})
            },
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "text": {
                                    "query": query_text,
                                    "boost": bm25_boost
                                }
                            }
                        }
                    ],
                    **({"filter": [case_filter]} if case_filter else {})
                }
            },
            "highlight": {
                "fields": {"text": {"fragment_size": 400, "number_of_fragments": 2}}
            }
        }
        res = self.es.search(index=index, body=body)
        self._log_query("hybrid", body)
        return res

    def delete_document(self, doc_id: str):
        """Delete a document by its doc_id."""
        try:
            res = self.es.delete(index=self.index_name, id=doc_id)
            self._log_query("delete", {"doc_id": doc_id})
            return res
        except Exception as e:
            print(f"Error deleting document {doc_id}: {e}")
            return None

# Usage Example:
# client = JPCourtESClient()
# results = client.hybrid_search("case_docs_index", "late answer rules", case_id="**********")
