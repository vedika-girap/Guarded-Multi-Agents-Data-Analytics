import re
import sqlite3

from app.config import DB_PATH


def search_documents(question: str, limit: int = 3) -> list[dict]:
    # FTS query terms are quoted individually, so user punctuation cannot alter the query.
    terms = re.findall(r"[\w]+", question, flags=re.UNICODE)[:12]
    if not terms:
        return []
    match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT doc_id, title, body, bm25(documents) AS score FROM documents "
            "WHERE documents MATCH ? ORDER BY score LIMIT ?", (match, limit)
        ).fetchall()
    return [{"source_id": row["doc_id"], "title": row["title"], "text": row["body"]} for row in rows]
