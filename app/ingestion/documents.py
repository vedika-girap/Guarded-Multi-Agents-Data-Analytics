"""Offline document ingestion for plain-text and Markdown files."""
import hashlib
import re
import sqlite3
from pathlib import Path

from app.config import DATA_DIR, DB_PATH, ROLE_LEVELS

CHUNK_CHARS = 1200
OVERLAP_CHARS = 160


def _chunks(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(clean):
        end = min(start + CHUNK_CHARS, len(clean))
        if end < len(clean):
            boundary = clean.rfind(" ", start + CHUNK_CHARS // 2, end)
            if boundary > start:
                end = boundary
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = max(start + 1, end - OVERLAP_CHARS)
    return chunks


def ingest_directory(directory: str | Path, tenant_id: str, min_role: str = "viewer") -> int:
    """Ingest .txt/.md files into FTS with explicit tenant and role metadata."""
    if min_role not in ROLE_LEVELS:
        raise ValueError(f"Unknown role: {min_role}")
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Document directory does not exist: {root}")
    if not tenant_id or len(tenant_id) > 200:
        raise ValueError("tenant_id must be between 1 and 200 characters")

    records = []
    source_root = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".txt", ".md"}):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        for number, body in enumerate(_chunks(text)):
            stable = f"{tenant_id}:{source_root}:{relative}:{number}:{body}"
            doc_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
            title = path.stem.replace("_", " ").replace("-", " ")
            records.append((doc_id, title, body, tenant_id, ROLE_LEVELS[min_role], relative, source_root, number))

    with sqlite3.connect(DB_PATH) as db:
        old_ids = {
            row[0] for row in db.execute(
                "SELECT doc_id FROM document_sources WHERE tenant_id=? AND source_root=?",
                (tenant_id, source_root),
            )
        }
        new_ids = {record[0] for record in records}
        stale_ids = sorted(old_ids - new_ids)
        for doc_id in old_ids:
            # FTS5 has no primary-key constraint; remove existing rows before
            # reinserting the current snapshot so reruns remain idempotent.
            db.execute("DELETE FROM documents WHERE doc_id=? AND tenant_id=?", (doc_id, tenant_id))
        db.execute("DELETE FROM document_sources WHERE tenant_id=? AND source_root=?", (tenant_id, source_root))
        for doc_id, title, body, record_tenant, role_level, source, record_root, chunk_number in records:
            db.execute(
                "INSERT OR REPLACE INTO documents(doc_id,title,body,tenant_id,min_role,source_name) VALUES(?,?,?,?,?,?)",
                (doc_id, title, body, record_tenant, role_level, source),
            )
            db.execute(
                "INSERT INTO document_sources(tenant_id,source_root,source_path,chunk_index,doc_id) VALUES(?,?,?,?,?)",
                (record_tenant, record_root, source, chunk_number, doc_id),
            )
    if records and (DATA_DIR / "chroma").exists():
        try:
            from app.retrieval.vector_store import sync_metadata

            sync_metadata([
                (record[0], record[1], record[3], record[4], record[5])
                for record in records
            ])
        except ImportError:
            pass
    if stale_ids and (DATA_DIR / "chroma").exists():
        try:
            from app.retrieval.vector_store import delete_documents

            delete_documents(stale_ids)
        except ImportError:
            # An absent optional vector index cannot affect BM25 access; stale IDs are
            # still removed from the authoritative document store above.
            pass
    return len(records)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest text and Markdown files into the local document index.")
    parser.add_argument("directory", help="Directory to scan recursively")
    parser.add_argument("--tenant-id", required=True, help="Tenant authorized to retrieve these documents")
    parser.add_argument("--min-role", choices=tuple(ROLE_LEVELS), default="viewer")
    args = parser.parse_args()
    print(f"Indexed {ingest_directory(args.directory, args.tenant_id, args.min_role)} document chunks")
