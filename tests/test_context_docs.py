from pathlib import Path

from app.config import Settings
from app.ingestion import documents, seed
from app.retrieval import search


def test_context_docs_are_tenant_scoped_and_retrievable(tmp_path, monkeypatch):
    db_path = tmp_path / "context.db"
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(documents, "DB_PATH", db_path)
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    monkeypatch.setattr(search, "DB_PATH", db_path)
    monkeypatch.setattr(search, "get_settings", lambda: Settings(_env_file=None))
    seed.initialize()

    root = Path(__file__).resolve().parents[1] / "docs" / "context"
    assert documents.ingest_directory(root / "tenant-a", "tenant-a", "viewer") == 4
    assert documents.ingest_directory(root / "tenant-b", "tenant-b", "viewer") == 4

    hits = search.search_documents(
        "Which documents explain how cancellations are handled?",
        tenant_id="tenant-a",
        role="viewer",
    )
    assert any("cancellation" in hit["text"].lower() for hit in hits)
    assert not search.search_documents(
        "cancellations are excluded",
        tenant_id="tenant-c",
        role="admin",
    )
