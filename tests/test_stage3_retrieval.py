import sqlite3

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.ingestion import documents, seed
from app.retrieval import search


def configure_db(tmp_path, monkeypatch):
    db = tmp_path / "documents.db"
    monkeypatch.setattr(seed, "DB_PATH", db)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(documents, "DB_PATH", db)
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    monkeypatch.setattr(search, "DB_PATH", db)
    monkeypatch.setattr(search, "get_settings", lambda: Settings(_env_file=None))
    seed.initialize()
    return db


def test_retrieval_filters_tenant_and_minimum_role(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "restricted.md").write_text("Orchid confidential acquisition forecast", encoding="utf-8")
    documents.ingest_directory(source, tenant_id="tenant-a", min_role="analyst")

    viewer = search.search_documents("Orchid acquisition forecast", tenant_id="tenant-a", role="viewer")
    analyst = search.search_documents("Orchid acquisition forecast", tenant_id="tenant-a", role="analyst")
    other_tenant = search.search_documents("Orchid acquisition forecast", tenant_id="tenant-b", role="admin")

    assert not any(result["source"] == "restricted.md" for result in viewer)
    assert any(result["source"] == "restricted.md" for result in analyst)
    assert not other_tenant


def test_directory_ingestion_chunks_and_is_idempotent(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    from app.retrieval import vector_store

    vector_store.collection.cache_clear()
    monkeypatch.setattr(vector_store, "DATA_DIR", tmp_path / "vectors")
    source = tmp_path / "source"
    source.mkdir()
    (source / "long.txt").write_text("analytics " * 300, encoding="utf-8")

    first_count = documents.ingest_directory(source, tenant_id="tenant-a")
    second_count = documents.ingest_directory(source, tenant_id="tenant-a")
    results = search.search_documents("analytics", tenant_id="tenant-a", role="viewer", limit=10)

    assert first_count > 1
    assert second_count == first_count
    assert len([result for result in results if result["source"] == "long.txt"]) == first_count

    (source / "long.txt").write_text("replacement policy content", encoding="utf-8")
    replacement_count = documents.ingest_directory(source, tenant_id="tenant-a")
    with sqlite3.connect(tmp_path / "documents.db") as db:
        chunk_count = db.execute("SELECT COUNT(*) FROM documents WHERE tenant_id='tenant-a'").fetchone()[0]
    assert replacement_count == 1
    assert chunk_count == replacement_count
    (source / "long.txt").unlink()
    assert documents.ingest_directory(source, tenant_id="tenant-a") == 0
    with sqlite3.connect(tmp_path / "documents.db") as db:
        assert db.execute("SELECT COUNT(*) FROM documents WHERE tenant_id='tenant-a'").fetchone()[0] == 0
    vector_store.collection.cache_clear()


def test_legacy_fts_documents_upgrade_without_losing_seed_content(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE VIRTUAL TABLE documents USING fts5(doc_id UNINDEXED,title,body)")
        db.execute("INSERT INTO documents VALUES('legacy_doc','Legacy','Legacy reporting definition')")
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(search, "DB_PATH", db_path)
    seed.initialize()

    hits = search.search_documents("Legacy reporting definition", tenant_id="local-dev-tenant", role="viewer")

    assert any(hit["source_id"] == "legacy_doc" for hit in hits)


def test_chroma_filters_tenant_and_minimum_role(tmp_path, monkeypatch):
    from app.retrieval import vector_store

    vector_store.collection.cache_clear()
    monkeypatch.setattr(vector_store, "DATA_DIR", tmp_path)
    vector_store.upsert_document("viewer-a", "Viewer", "visible", "tenant-a", 0, "v.md", [1.0, 0.0])
    vector_store.upsert_document("analyst-a", "Analyst", "restricted", "tenant-a", 1, "a.md", [0.99, 0.01])
    vector_store.upsert_document("viewer-b", "Other tenant", "private", "tenant-b", 0, "b.md", [1.0, 0.0])

    viewer_ids = vector_store.search([1.0, 0.0], "tenant-a", min_role=0)
    analyst_ids = vector_store.search([1.0, 0.0], "tenant-a", min_role=1)

    assert "viewer-a" in viewer_ids
    assert "analyst-a" not in viewer_ids
    assert "analyst-a" in analyst_ids
    assert "viewer-b" not in analyst_ids
    vector_store.collection.cache_clear()


def test_reingestion_syncs_changed_role_metadata_to_chroma(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    from app.retrieval import vector_store

    vector_store.collection.cache_clear()
    vector_root = tmp_path / "vector_data"
    monkeypatch.setattr(vector_store, "DATA_DIR", vector_root)
    monkeypatch.setattr(documents, "DATA_DIR", vector_root)
    source = tmp_path / "source"
    source.mkdir()
    (source / "report.md").write_text("Quarterly forecasts are documented here.", encoding="utf-8")
    documents.ingest_directory(source, tenant_id="tenant-a", min_role="viewer")
    with sqlite3.connect(tmp_path / "documents.db") as db:
        doc_id = db.execute("SELECT doc_id FROM documents WHERE tenant_id='tenant-a'").fetchone()[0]
    vector_store.upsert_document(doc_id, "report", "Quarterly forecasts are documented here.", "tenant-a", 0, "report.md", [1.0, 0.0])

    documents.ingest_directory(source, tenant_id="tenant-a", min_role="analyst")
    metadata = vector_store.collection().get(ids=[doc_id], include=["metadatas"])["metadatas"][0]

    assert metadata["min_role"] == 1
    vector_store.collection.cache_clear()


def test_no_embedding_call_when_tenant_has_no_chroma_vectors(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    from app.retrieval import embeddings, vector_store

    vector_store.collection.cache_clear()
    monkeypatch.setattr(vector_store, "DATA_DIR", tmp_path / "empty-index")
    monkeypatch.setattr(
        search, "get_settings",
        lambda: Settings(gemini_api_key=SecretStr("test-key"), _env_file=None),
    )
    monkeypatch.setattr(embeddings, "embed", lambda *args, **kwargs: pytest.fail("embedding call should be skipped"))

    results = search.search_documents("How is fiscal year defined?", tenant_id="tenant-a", role="viewer")

    assert results == []
