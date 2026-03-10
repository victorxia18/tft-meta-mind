"""ChromaDB wrapper for TFT knowledge storage and retrieval.

Manages a ChromaDB collection for storing and querying TFT meta
documents with semantic search.

Usage:
    python -m rag.vector_store
"""

import hashlib
import logging
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)


class TFTVectorStore:
    """ChromaDB-backed vector store for TFT knowledge."""

    def __init__(self, persist_dir: str = "./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name="tft_knowledge",
            embedding_function=self.embedding_fn,
            metadata={"description": "TFT meta knowledge base"},
        )

    def _chunk_by_sections(self, text: str) -> list[str]:
        """Split text on '## ' headers so each comp/unit stays in one chunk.

        Falls back to the full text as a single chunk if no headers found.
        """
        chunks = []
        current = ""

        for line in text.split("\n"):
            if line.startswith("## ") and current.strip():
                chunks.append(current.strip())
                current = ""
            current += line + "\n"

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def ingest_document(self, document: dict):
        """Ingest a generated document into the vector store.

        Args:
            document: {"text": str, "metadata": dict} where metadata
                      has keys like source, type, date, patch.
        """
        text = document["text"]
        base_metadata = document.get("metadata", {})

        chunks = self._chunk_by_sections(text)

        ids = []
        documents = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            # Deterministic ID from type + date + chunk index
            # Re-running ingestion will upsert (update) instead of duplicate
            raw_id = f"{base_metadata.get('type', '')}_{base_metadata.get('date', '')}_{i}"
            chunk_id = hashlib.md5(raw_id.encode()).hexdigest()

            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({**base_metadata, "chunk_index": i})

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

        logger.info(
            "Ingested %d chunks from %s", len(chunks), base_metadata.get("type", "unknown")
        )
        print(f"Ingested {len(chunks)} chunks from {base_metadata.get('type', 'unknown')}")

    def query(
        self,
        question: str,
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Retrieve the most relevant chunks for a question.

        Args:
            question: Natural language query.
            n_results: Number of chunks to return.
            where: Optional ChromaDB metadata filter.

        Returns:
            List of {"text": str, "metadata": dict, "distance": float}.
        """
        kwargs = {
            "query_texts": [question],
            "n_results": min(n_results, self.collection.count()),
        }
        if where:
            kwargs["where"] = where

        if kwargs["n_results"] == 0:
            return []

        results = self.collection.query(**kwargs)

        output = []
        for i in range(len(results["documents"][0])):
            output.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })

        return output

    def get_stats(self) -> dict:
        """Return collection statistics."""
        return {"total_chunks": self.collection.count()}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Initializing vector store...")
    store = TFTVectorStore()
    print(f"Current stats: {store.get_stats()}")

    # Ingest a sample document
    sample_doc = {
        "text": (
            "# TFT Test Document\n\n"
            "## Comp 1: Void Reroll\n"
            "Average Placement: 3.13 | Win Rate: 16.2%\n"
            "Core Units: Cho'Gath, Malzahar, Nautilus\n\n"
            "## Comp 2: Targon Carry\n"
            "Average Placement: 3.50 | Win Rate: 12.0%\n"
            "Core Units: Leona, Taric, Zoe\n"
        ),
        "metadata": {
            "source": "test",
            "type": "test_snapshot",
            "date": "2026-01-01",
            "patch": "current",
        },
    }

    print("\nIngesting sample document...")
    store.ingest_document(sample_doc)
    print(f"Stats after ingestion: {store.get_stats()}")

    # Test queries
    test_queries = [
        "what comps are strong right now",
        "what units should I play with Cho'Gath",
        "best Targon comp",
    ]

    for q in test_queries:
        print(f"\nQ: {q}")
        results = store.query(q, n_results=2)
        for r in results:
            preview = r["text"][:120].replace("\n", " ")
            print(f"  [{r['metadata']['type']}] (dist={r['distance']:.3f}) {preview}...")
