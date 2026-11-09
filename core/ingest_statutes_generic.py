import os
"""
Generic Statute Extractor + Ingester
=====================================
Extracts sections/rules from a Texas statute PDF and ingests them into
statutes_index with 768-dim all-mpnet-base-v2 embeddings.

Chunking strategy:
  - Split at section/rule boundaries first
  - Then sub-chunk each section body into 300-600 char pieces
  - Split on sentence boundaries ('. ') to preserve meaning
  - Never split mid-sentence unless a single sentence exceeds 600 chars

Usage:
  python ingest_statutes_generic.py \
    --pdf "path/to/statute.pdf" \
    --title "Texas Rules of Civil Procedure" \
    --pattern trcp \
    --out trcp_sections.json \
    [--ingest]

Patterns:
  trcp       Matches: Rule 501.1, RULE 502.5, Rule 1, etc.
  sec        Matches: Sec. 132.001, Sec. 545.062, etc.
  auto       Tries trcp first, falls back to sec
"""

import re
import json
import argparse
from pathlib import Path

from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from elasticsearch import Elasticsearch
from tqdm import tqdm

# ── Config ────────────────────────────────────────────────────────────────────

ES_URL     = "http://localhost:9200"
ES_API_KEY = os.environ.get("ES_API_KEY", "")
ES_INDEX   = "statutes_index"
MODEL_NAME = "all-mpnet-base-v2"

MIN_CHUNK  = 100   # discard chunks shorter than this (noise/headers)
MAX_CHUNK  = 600   # target max chunk size in characters
SOFT_MIN   = 300   # try to keep chunks above this before merging

# ── Regex patterns ─────────────────────────────────────────────────────────────

PATTERNS = {
    "trcp": re.compile(
        r"(?:^|\n)((?:RULE|Rule)\s+\d+[a-zA-Z]?(?:\.\d+)?\.?\s+[A-Z][^\n]{3,80})",
        re.MULTILINE
    ),
    "sec": re.compile(
        r"(?:^|\n)(Sec\.\s+[A-Z]?\s*\d+[a-zA-Z]?\.\d+[a-zA-Z]?\.\s+[A-Z][^\n]{3,80})",
        re.MULTILINE
    ),
}

# ── PDF extraction ─────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            pages.append(t)
    return "\n".join(pages)


# ── Section splitting ──────────────────────────────────────────────────────────

def split_into_sections(text: str, pattern_key: str) -> list[dict]:
    """Split full statute text into {heading, body} dicts at rule/section boundaries."""
    if pattern_key == "auto":
        # Try trcp first, fall back to sec
        sections = _split(text, PATTERNS["trcp"])
        if len(sections) < 5:
            sections = _split(text, PATTERNS["sec"])
        return sections
    return _split(text, PATTERNS[pattern_key])


def _split(text: str, pattern: re.Pattern) -> list[dict]:
    parts = pattern.split(text)
    sections = []
    current = None

    for part in parts:
        if pattern.search(part) and len(part.strip()) < 120:
            # This is a heading
            if current and current["body"].strip():
                sections.append(current)
            current = {"heading": part.strip(), "body": ""}
        else:
            if current is not None:
                current["body"] += part
            # else: preamble before first section — skip

    if current and current["body"].strip():
        sections.append(current)

    return sections


# ── Section number extraction ──────────────────────────────────────────────────

def extract_section_number(heading: str) -> str:
    # TRCP: Rule 502.5, RULE 501, Rule 1
    m = re.search(r"(?:RULE|Rule)\s+(\d+[a-zA-Z]?(?:\.\d+)?)", heading)
    if m:
        return m.group(1)
    # CPRC/TTC: Sec. 132.001, Sec. A 6.01
    m = re.search(r"Sec\.\s*[A-Z]?\s*(\d+[a-zA-Z]?\.\d+[a-zA-Z]?)", heading)
    if m:
        return m.group(1)
    return "UNKNOWN"


# ── Smart chunker ──────────────────────────────────────────────────────────────

def smart_chunks(text: str, max_size: int = MAX_CHUNK, soft_min: int = SOFT_MIN) -> list[str]:
    """
    Split text into chunks of ~300-600 chars.
    Strategy:
      1. Split on '. ' (sentence boundary)
      2. Accumulate sentences until approaching max_size
      3. If a single sentence > max_size, split on '; ' or ', ' or hard-cut
    """
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    # Split into sentences
    raw_sentences = re.split(r"(?<=\.)\s+", text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    chunks = []
    current = ""

    for sentence in sentences:
        # If single sentence is too long, sub-split it
        if len(sentence) > max_size:
            # Flush current first
            if current.strip():
                chunks.append(current.strip())
                current = ""
            # Sub-split on semicolons or commas
            sub_parts = re.split(r"(?<=;)\s+|(?<=,)\s+(?=[A-Z(])", sentence)
            sub_buf = ""
            for sp in sub_parts:
                if len(sub_buf) + len(sp) + 1 <= max_size:
                    sub_buf = (sub_buf + " " + sp).strip()
                else:
                    if sub_buf:
                        chunks.append(sub_buf)
                    sub_buf = sp
            if sub_buf:
                chunks.append(sub_buf)
            continue

        # Normal accumulation
        candidate = (current + " " + sentence).strip()
        if len(candidate) <= max_size:
            current = candidate
        else:
            # Flush if above soft_min, else keep accumulating
            if len(current) >= soft_min:
                chunks.append(current)
                current = sentence
            else:
                # Below soft_min — keep going even if over max
                current = candidate

    if current.strip():
        chunks.append(current.strip())

    # Filter noise
    return [c for c in chunks if len(c) >= MIN_CHUNK]


# ── Main pipeline ──────────────────────────────────────────────────────────────

def extract_and_chunk(pdf_path: str, pattern_key: str, title: str) -> list[dict]:
    """Extract PDF → split sections → chunk bodies → return list of chunk dicts."""
    print(f"[READ] {pdf_path}")
    text = extract_pdf_text(pdf_path)

    print(f"[SPLIT] Using pattern: {pattern_key}")
    sections = split_into_sections(text, pattern_key)
    print(f"[SPLIT] Found {len(sections)} sections")

    chunks = []
    for sec in sections:
        heading = sec["heading"].strip()
        body    = sec["body"].strip()
        section_number = extract_section_number(heading)

        if not body:
            continue

        body_chunks = smart_chunks(body)

        for i, chunk_text in enumerate(body_chunks):
            chunks.append({
                "title":       title,
                "section":     section_number,
                "heading":     heading,
                "chunk_index": i,
                "chunk_total": len(body_chunks),
                "jurisdiction": "Texas",
                "text":        chunk_text,
                "source_file": Path(pdf_path).name
            })

    print(f"[CHUNK] {len(chunks)} chunks from {len(sections)} sections")
    return chunks


def save_json(chunks: list[dict], out_path: str):
    Path(out_path).write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[SAVE] {len(chunks)} chunks -> {out_path}")


def ingest_to_es(chunks: list[dict], title: str):
    print(f"[ES] Connecting to {ES_URL}")
    es = Elasticsearch(ES_URL, api_key=ES_API_KEY)
    model = SentenceTransformer(MODEL_NAME)

    print(f"[EMBED+INGEST] {len(chunks)} chunks into {ES_INDEX}")
    for chunk in tqdm(chunks, desc="Ingesting"):
        embedding = model.encode(chunk["text"]).tolist()
        doc = {
            "title":       chunk["title"],
            "section":     chunk["section"],
            "heading":     chunk["heading"],
            "jurisdiction": chunk["jurisdiction"],
            "text":        chunk["text"],
            "embedding":   embedding,
            "source_file": chunk["source_file"],
            "chunk_index": chunk["chunk_index"],
            "chunk_total": chunk["chunk_total"],
        }
        es.index(index=ES_INDEX, document=doc)

    print(f"[OK] Ingested {len(chunks)} chunks into {ES_INDEX}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract and ingest Texas statute PDF into Elasticsearch")
    parser.add_argument("--pdf",     required=True,  help="Path to statute PDF")
    parser.add_argument("--title",   required=True,  help="Human-readable title, e.g. 'Texas Rules of Civil Procedure'")
    parser.add_argument("--pattern", default="auto", choices=["trcp", "sec", "auto"],
                        help="Section heading pattern: trcp (Rule X.X), sec (Sec. X.X), auto (detect)")
    parser.add_argument("--out",     default=None,   help="Output JSON path (optional, defaults to <title>.json)")
    parser.add_argument("--ingest",  action="store_true", help="Ingest into Elasticsearch after extraction")
    parser.add_argument("--from-json", default=None, help="Skip extraction, ingest from existing JSON file")
    args = parser.parse_args()

    if args.from_json:
        # Ingest from existing JSON
        chunks = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        print(f"[LOAD] {len(chunks)} chunks from {args.from_json}")
        ingest_to_es(chunks, args.title)
        return

    # Extract + chunk
    chunks = extract_and_chunk(args.pdf, args.pattern, args.title)

    # Save JSON
    out_path = args.out or (args.title.lower().replace(" ", "_") + "_chunks.json")
    save_json(chunks, out_path)

    # Optionally ingest
    if args.ingest:
        ingest_to_es(chunks, args.title)
    else:
        print(f"\n[NEXT] To ingest, run:")
        print(f"  python ingest_statutes_generic.py --from-json {out_path} --title \"{args.title}\" --pdf {args.pdf}")
        print(f"  or re-run with --ingest flag")


if __name__ == "__main__":
    main()
