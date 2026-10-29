"""Create/update Gemini vectors for the current local document corpus."""
import sqlite3

from app.config import DB_PATH, get_settings
from app.ingestion.seed import initialize
from app.retrieval.embeddings import embed
from app.retrieval.vector_store import collection, upsert_document


def main() -> None:
    if get_settings().gemini_api_key is None:
        raise SystemExit("Set GEMINI_API_KEY in .env before building semantic vectors.")
    initialize()
    settings = get_settings()
    with sqlite3.connect(DB_PATH) as db:
        docs = db.execute("SELECT doc_id,title,body,tenant_id,min_role,source_name FROM documents ORDER BY doc_id").fetchall()
    vector_collection = collection()
    indexed = set(vector_collection.get(include=["metadatas"])["ids"])
    active_ids = {row[0] for row in docs}
    stale_ids = sorted(indexed - active_ids)
    if stale_ids:
        vector_collection.delete(ids=stale_ids)
    pending = [row for row in docs if row[0] not in indexed]

    for doc_id, title, body, tenant_id, min_role, source in pending:
        vector = embed(body, "RETRIEVAL_DOCUMENT", title=title)
        upsert_document(doc_id, title, body, tenant_id, min_role, source, vector)
    print(f"Indexed {len(pending)} document vectors; removed {len(stale_ids)} stale vectors.")


if __name__ == "__main__":
    main()
