import os
from sentence_transformers import SentenceTransformer
import json
import uuid

# Load model once
model = SentenceTransformer("all-mpnet-base-v2")

def prompt_input(prompt_text, required=True):
    while True:
        value = input(prompt_text).strip()
        if value or not required:
            return value
        print("This field is required.")

def main():
    print("\n=== CASE DOCUMENT INGESTION ===\n")

    # Collect fields
    title = prompt_input("Enter document title: ")
    doc_type = prompt_input("Enter document type (e.g., petition, estimate, email): ")
    date_str = prompt_input("Enter document date (YYYY-MM-DD): ")
    source_file = prompt_input("Enter source filename (optional): ", required=False)
    tags_raw = prompt_input("Enter tags (comma-separated, optional): ", required=False)
    text = prompt_input("\nPaste document text below:\n")

    # Process tags
    tags = [t.strip() for t in tags_raw.split(",")] if tags_raw else []

    # Generate embedding
    print("\nGenerating embedding...")
    embedding = model.encode(text).tolist()

    # Generate doc_id
    doc_id = "DOC-" + str(uuid.uuid4())[:8].upper()

    # Build document
    doc = {
        "doc_id": doc_id,
        "case_id": os.environ.get("CASE_ID", "YOUR-CASE-ID"),
        "type": doc_type,
        "title": title,
        "text": text,
        "date": date_str,
        "source_file": source_file,
        "tags": tags,
        "embedding": embedding
    }

    # Output Kibana command
    print("\n\n=== PASTE INTO KIBANA DEV TOOLS ===\n")
    print(f"PUT case_docs_index/_doc/{doc_id}")
    print(json.dumps(doc, indent=2))
    print("\n=== END ===\n")


if __name__ == "__main__":
    main()
