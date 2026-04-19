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
from chromadb.errors import NotFoundError
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

    # Chunks beyond this character count get sub-chunked on ### headers
    MAX_CHUNK_CHARS = 1500

    def _chunk_by_sections(self, text: str) -> list[str]:
        """Split text on '## ' headers, then sub-split oversized chunks on '### '.

        Keeps each comp/unit together when possible, but breaks apart very large
        sections so they stay within the embedding model's effective context window.
        Falls back to the full text as a single chunk if no headers found.
        """
        # First pass: split on ## headers
        raw_chunks = []
        current = ""

        for line in text.split("\n"):
            if line.startswith("## ") and current.strip():
                raw_chunks.append(current.strip())
                current = ""
            current += line + "\n"

        if current.strip():
            raw_chunks.append(current.strip())

        # Second pass: sub-split oversized chunks on ### headers
        chunks = []
        for chunk in raw_chunks:
            if len(chunk) <= self.MAX_CHUNK_CHARS:
                chunks.append(chunk)
                continue

            # Try splitting on ### headers
            section_header = ""
            sub_chunks = []
            sub_current = ""

            for line in chunk.split("\n"):
                # Capture the ## header to prepend to sub-chunks for context
                if line.startswith("## "):
                    section_header = line
                    sub_current += line + "\n"
                    continue

                if line.startswith("### ") and sub_current.strip():
                    sub_chunks.append(sub_current.strip())
                    # Prepend section header to each sub-chunk for context
                    sub_current = section_header + "\n\n" if section_header else ""

                sub_current += line + "\n"

            if sub_current.strip():
                sub_chunks.append(sub_current.strip())

            # Only use sub-chunks if splitting actually helped
            if len(sub_chunks) > 1:
                chunks.extend(sub_chunks)
            else:
                chunks.append(chunk)

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
            # Deterministic ID from type + date + source_id + chunk index
            # Re-running ingestion will upsert (update) instead of duplicate
            # Include video_id (if present) so multiple videos on the same date don't collide
            source_id = base_metadata.get("video_id", "")
            raw_id = f"{base_metadata.get('type', '')}_{base_metadata.get('date', '')}_{source_id}_{i}"
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

    def _refresh_collection(self):
        """Re-fetch collection reference when the stored UUID becomes stale."""
        logger.warning("Collection reference stale — re-fetching from client")
        self.collection = self.client.get_or_create_collection(
            name="tft_knowledge",
            embedding_function=self.embedding_fn,
            metadata={"description": "TFT meta knowledge base"},
        )

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
        try:
            current_count = self.collection.count()
        except NotFoundError:
            self._refresh_collection()
            current_count = self.collection.count()

        kwargs = {
            "query_texts": [question],
            "n_results": min(n_results, current_count),
        }
        if where:
            kwargs["where"] = where

        if kwargs["n_results"] == 0:
            return []

        try:
            results = self.collection.query(**kwargs)
        except Exception as e:
            if where:
                # Filtered query failed (likely index/metadata desync) — retry without filter
                logger.warning(
                    "Filtered query failed (%s), retrying without filter: %s",
                    where, e,
                )
                kwargs.pop("where")
                try:
                    results = self.collection.query(**kwargs)
                except Exception:
                    logger.error("Query failed even without filter: %s", e)
                    return []
            else:
                logger.error("Query failed: %s", e)
                return []

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
        try:
            return {"total_chunks": self.collection.count()}
        except NotFoundError:
            self._refresh_collection()
            return {"total_chunks": self.collection.count()}

    def get_all_metadata(self) -> list[dict]:
        """Return metadata for every chunk in the collection."""
        try:
            count = self.collection.count()
        except NotFoundError:
            self._refresh_collection()
            count = self.collection.count()
        if count == 0:
            return []
        result = self.collection.get(include=["metadatas"])
        return result["metadatas"]

    def get_chunks_by_filter(
        self, where: dict, include_documents: bool = False
    ) -> dict:
        """Return chunk IDs (and optionally text) matching a metadata filter."""
        include = ["metadatas"]
        if include_documents:
            include.append("documents")
        result = self.collection.get(where=where, include=include)
        return result

    def delete_by_filter(self, where: dict) -> int:
        """Delete all chunks matching a metadata filter. Returns count deleted."""
        result = self.collection.get(where=where, include=[])
        ids = result["ids"]
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def delete_by_ids(self, ids: list[str]) -> int:
        """Delete chunks by their IDs. Returns count deleted."""
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def reset_collection(self):
        """Delete and recreate the collection. Use when the index is corrupted."""
        logger.warning("Resetting collection 'tft_knowledge' due to corruption")
        self.client.delete_collection("tft_knowledge")
        self.collection = self.client.get_or_create_collection(
            name="tft_knowledge",
            embedding_function=self.embedding_fn,
            metadata={"description": "TFT meta knowledge base"},
        )
        logger.info("Collection reset complete — re-ingestion required")


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
