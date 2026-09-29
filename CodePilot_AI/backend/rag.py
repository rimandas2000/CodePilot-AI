"""Local ChromaDB retrieval helpers for CodePilot AI."""
from pathlib import Path

import chromadb

DB_PATH = Path(__file__).resolve().parent.parent / "chroma_db"
COLLECTION_NAME = "coding_knowledge"


def get_collection():
    client = chromadb.PersistentClient(path=str(DB_PATH))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def retrieve(query: str, n_results: int = 5):
    """Return matching local knowledge entries, or [] if retrieval is unavailable."""
    try:
        collection = get_collection()
        count = collection.count()
        if count == 0:
            return []
        result = collection.query(
            query_texts=[query],
            n_results=min(max(int(n_results), 1), count),
        )
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        return [
            {"text": doc, "source": (meta or {}).get("source", "Unknown")}
            for doc, meta in zip(docs, metas)
        ]
    except Exception:
        # The AI remains usable even if the local vector store has not yet
        # been ingested or an embedding dependency is unavailable.
        return []
