from pathlib import Path
import hashlib
import chromadb

ROOT = Path(__file__).resolve().parent
KNOWLEDGE = ROOT / "knowledge"
DB_PATH = ROOT.parent / "chroma_db"

def chunk_text(text, chunk_size=900, overlap=150):
    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap

    return chunks

def main():
    client = chromadb.PersistentClient(path=str(DB_PATH))
    collection = client.get_or_create_collection(
        name="coding_knowledge",
        metadata={"hnsw:space": "cosine"},
    )

    documents, ids, metadatas = [], [], []

    for path in KNOWLEDGE.rglob("*"):
        if path.suffix.lower() not in {".md", ".txt"}:
            continue

        text = path.read_text(encoding="utf-8")
        chunks = chunk_text(text)

        for i, chunk in enumerate(chunks):
            digest = hashlib.sha1(
                f"{path.name}-{i}-{chunk}".encode("utf-8")
            ).hexdigest()

            ids.append(digest)
            documents.append(chunk)
            metadatas.append({"source": path.name, "chunk": i})

    if documents:
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

    print(f"Indexed {len(documents)} knowledge chunks.")
    print(f"Vector database: {DB_PATH}")

if __name__ == "__main__":
    main()
