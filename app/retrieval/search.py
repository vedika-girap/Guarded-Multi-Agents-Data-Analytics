"""Access-filtered BM25 retrieval with optional Chroma semantic fusion."""
import re
import sqlite3
import logging

from app.config import DB_PATH, ROLE_LEVELS, get_settings

logger = logging.getLogger(__name__)


def search_documents(
    question: str, limit: int = 3, tenant_id: str = "local-dev-tenant", role: str = "viewer",
) -> list[dict]:
    if role not in ROLE_LEVELS or not tenant_id:
        return []
    terms = re.findall(r"[\w]+", question, flags=re.UNICODE)[:12]
    if not terms:
        return []
    match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        allowed = db.execute(
            "SELECT doc_id,title,body,source_name,bm25(documents) AS score FROM documents "
            "WHERE documents MATCH ? AND tenant_id=? AND CAST(min_role AS INTEGER)<=? "
            "ORDER BY score LIMIT 50",
            (match, tenant_id, ROLE_LEVELS[role]),
        ).fetchall()
    lexical = {row["doc_id"]: row for row in allowed}
    if get_settings().gemini_api_key is not None:
        try:
            from app.retrieval.embeddings import embed
            from app.retrieval.vector_store import has_documents, search as chroma_search

            if not has_documents(tenant_id, ROLE_LEVELS[role]):
                return [_format(row) for row in allowed[:limit]]
            vector_ids = chroma_search(
                embed(question, "RETRIEVAL_QUERY"), tenant_id, ROLE_LEVELS[role], limit=50,
            )
            if not vector_ids:
                return [_format(row) for row in allowed[:limit]]
            placeholders = ",".join("?" for _ in vector_ids)
            # Re-check vector-store results against authoritative SQLite access metadata.
            with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                semantic = db.execute(
                    f"SELECT doc_id,title,body,source_name FROM documents "
                    f"WHERE doc_id IN ({placeholders}) AND tenant_id=? AND CAST(min_role AS INTEGER)<=?",
                    (*vector_ids, tenant_id, ROLE_LEVELS[role]),
                ).fetchall()
            semantic_by_id = {row["doc_id"]: row for row in semantic}
            semantic_ids = [doc_id for doc_id in vector_ids if doc_id in semantic_by_id]
            # Reciprocal-rank fusion combines incomparable BM25 and cosine scores.
            fusion: dict[str, float] = {}
            for rank, row in enumerate(allowed):
                fusion[row["doc_id"]] = fusion.get(row["doc_id"], 0) + 1 / (60 + rank + 1)
            for rank, doc_id in enumerate(semantic_ids):
                fusion[doc_id] = fusion.get(doc_id, 0) + 1 / (60 + rank + 1)
            by_id = lexical | semantic_by_id
            ranked_ids = sorted(fusion, key=fusion.get, reverse=True)[:limit]
            return [_format(by_id[doc_id]) for doc_id in ranked_ids if doc_id in by_id]
        except Exception as exc:
            # Missing/stale Chroma index or provider issues retain BM25 behavior.
            logger.warning("Semantic retrieval failed; using BM25 fallback (%s)", type(exc).__name__)

    return [_format(row) for row in allowed[:limit]]


def _format(row) -> dict:
    return {
        "source_id": row["doc_id"], "title": row["title"], "text": row["body"],
        "source": row["source_name"],
    }
