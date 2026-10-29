"""Persistent Chroma vector store for local development and testing."""
from functools import lru_cache
import hashlib

from app.config import DATA_DIR, get_settings


def _collection_name() -> str:
    model = get_settings().gemini_embedding_model
    suffix = hashlib.sha256(model.encode("utf-8")).hexdigest()[:10]
    return f"analytics_docs_{suffix}"


@lru_cache(maxsize=1)
def collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"))
    return client.get_or_create_collection(name=_collection_name(), metadata={"hnsw:space": "cosine"})


def upsert_document(doc_id: str, title: str, body: str, tenant_id: str, min_role: int, source: str, vector: list[float]) -> None:
    collection().upsert(
        ids=[doc_id], embeddings=[vector], documents=[body],
        metadatas=[{"title": title, "tenant_id": tenant_id, "min_role": min_role, "source": source}],
    )


def delete_documents(doc_ids: list[str]) -> None:
    if doc_ids:
        collection().delete(ids=doc_ids)


def sync_metadata(records: list[tuple[str, str, str, int, str]]) -> None:
    """Refresh access metadata for already-embedded documents without re-embedding."""
    target = collection()
    for start in range(0, len(records), 500):
        batch = records[start:start + 500]
        ids = [record[0] for record in batch]
        existing = set(target.get(ids=ids, include=["metadatas"])["ids"])
        updates = [record for record in batch if record[0] in existing]
        if updates:
            target.update(
                ids=[record[0] for record in updates],
                metadatas=[
                    {"title": record[1], "tenant_id": record[2], "min_role": record[3], "source": record[4]}
                    for record in updates
                ],
            )


def search(vector: list[float], tenant_id: str, min_role: int, limit: int = 50) -> list[str]:
    result = collection().query(
        query_embeddings=[vector],
        n_results=limit,
        where={"$and": [
            {"tenant_id": {"$eq": tenant_id}},
            {"min_role": {"$lte": min_role}},
        ]},
        include=["metadatas"],
    )
    return result["ids"][0] if result.get("ids") else []


def has_documents(tenant_id: str, min_role: int) -> bool:
    if not (DATA_DIR / "chroma").exists():
        return False
    return collection().count(where={"$and": [
        {"tenant_id": {"$eq": tenant_id}},
        {"min_role": {"$lte": min_role}},
    ]}) > 0
