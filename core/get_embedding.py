"""
get_embedding.py
================
Universal standalone utility to generate 768-dim embeddings using all-mpnet-base-v2.
Used in the 'Man-in-the-middle' protocol to provide high-precision vectors for 
hybrid search retrieval.

Usage:
    python get_embedding.py "your text here"
    OR
    python get_embedding.py (and follow the prompt)
"""

import sys
import json
from sentence_transformers import SentenceTransformer

def main():
    # Load the model specified in Requirement 2.1
    model = SentenceTransformer("all-mpnet-base-v2")

    # Get input text from CLI args or prompt
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = input("Enter text to embed: ").strip()

    if not text:
        print(json.dumps({"error": "No input text provided."}))
        sys.exit(1)

    # Generate embedding
    embedding = model.encode(text).tolist()

    # Output as JSON for easy copy-pasting or piping
    output = {
        "text_length": len(text),
        "embedding": embedding
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()