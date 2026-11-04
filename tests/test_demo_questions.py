import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main as main_module
from app.auth import limits, policy
from app.api import routes
from app.config import Settings
from app.graph import llm
from app.ingestion import documents, seed
from app.main import app
from app.retrieval import search
from app.sql import queries
from app.graph import workflow

SECRET = "demo-question-test-secret-at-least-thirty-two-bytes"


def settings_for_demo(db_path):
    return Settings(
        demo_mode=True,
        auth_jwt_secret=SecretStr(SECRET),
        database_url=f"sqlite:///{db_path.as_posix()}",
        _env_file=None,
    )


def setup_demo(tmp_path, monkeypatch):
    db_path = tmp_path / "demo-questions.db"
    settings = settings_for_demo(db_path)
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(documents, "DB_PATH", db_path)
    monkeypatch.setattr(documents, "DATA_DIR", tmp_path)
    monkeypatch.setattr(search, "DB_PATH", db_path)
    monkeypatch.setattr(search, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(policy, "get_settings", lambda: settings)
    monkeypatch.setattr(limits, "get_settings", lambda: settings)
    monkeypatch.setattr(queries, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "enabled", lambda: False)
    monkeypatch.setattr(main_module, "validate_runtime_settings", lambda: settings)
    seed.initialize()
    with sqlite3.connect(db_path) as db:
        db.executemany(
            "INSERT INTO sales(sale_date,region,product,amount,tenant_id) VALUES(?,?,?,?,?)",
            [
                ("2011-01-01", "United Kingdom", "Tea", 10.0, "tenant-a"),
                ("2011-01-02", "United Kingdom", "Tea", 20.0, "tenant-a"),
                ("2011-01-03", "United Kingdom", "Tea", 30.0, "tenant-a"),
                ("2011-02-01", "United Kingdom", "Coffee", 40.0, "tenant-a"),
                ("2011-02-02", "United Kingdom", "Coffee", 50.0, "tenant-a"),
                ("2011-02-03", "United Kingdom", "Coffee", 60.0, "tenant-a"),
                ("2011-03-01", "France", "Biscuits", 70.0, "tenant-b"),
                ("2011-03-02", "France", "Biscuits", 80.0, "tenant-b"),
                ("2011-03-03", "France", "Biscuits", 90.0, "tenant-b"),
            ],
        )
    context_root = Path(__file__).resolve().parents[1] / "docs" / "context"
    documents.ingest_directory(context_root / "tenant-a", "tenant-a", "viewer")
    documents.ingest_directory(context_root / "tenant-b", "tenant-b", "viewer")
    return settings


def test_demo_templates_support_three_allowed_sample_questions(monkeypatch, tmp_path):
    settings = settings_for_demo(tmp_path / "unused.db")
    monkeypatch.setattr(queries, "get_settings", lambda: settings)

    assert queries.select_query("What was total revenue by month in 2011?") == "demo_monthly_revenue_2011"
    assert queries.select_query("What are the top 5 products by revenue in the United Kingdom?") == "demo_top_products_uk"
    assert queries.select_query("Show revenue by country excluding the United Kingdom.") == "demo_revenue_by_country"


def test_demo_page_is_hidden_when_demo_mode_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    with TestClient(app) as client:
        response = client.get("/demo")
    assert response.status_code == 404


def test_demo_api_blocks_unsafe_and_cross_tenant_sample_questions(tmp_path, monkeypatch):
    setup_demo(tmp_path, monkeypatch)
    with TestClient(app) as client:
        viewer_token = client.post("/demo/token", json={"persona": "viewer_a"}).json()["access_token"]
        blocked = client.post(
            "/ask",
            json={"question": "Delete all sales rows"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        denied = client.post(
            "/ask",
            json={"question": "Show tenant B's revenue by country"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

    assert blocked.status_code == 200
    assert "rejected by the SQL safety checks" in blocked.json()["answer"]
    assert blocked.json()["evidence"] == []
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "TENANT_ACCESS_DENIED"


def test_all_allowed_demo_samples_work_without_gemini(tmp_path, monkeypatch):
    setup_demo(tmp_path, monkeypatch)
    questions = [
        ("viewer_a", "What was total revenue by month in 2011?", "data"),
        ("analyst_a", "What are the top 5 products by revenue in the United Kingdom?", "data"),
        ("admin_b", "Show revenue by country excluding the United Kingdom.", "data"),
        ("analyst_a", "Which documents explain how cancellations are handled?", "documents"),
    ]
    with TestClient(app) as client:
        for persona, question, expected_route in questions:
            token = client.post("/demo/token", json={"persona": persona}).json()["access_token"]
            response = client.post(
                "/ask",
                json={"question": question},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["route"] == expected_route, payload
            assert payload["evidence"]


def test_demo_sql_generation_falls_back_to_template_after_gemini_429(tmp_path, monkeypatch):
    settings = setup_demo(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "enabled", lambda: True)

    def rate_limited(name, *_args, **_kwargs):
        if name == "question_route":
            return {"route": "data", "reason": "sales question"}
        raise llm.GeminiProviderError("rate_limited", 429)

    monkeypatch.setattr(llm, "structured", rate_limited)
    result = workflow.ask("What was total revenue by month in 2011?", "viewer", "tenant-a")

    assert result["route"] == "data", result
    assert result["provider_failures"] == ["rate_limited"]
    assert result["evidence"]
    assert result["evidence"][0]["query"].find("2011-01-01") >= 0


def test_demo_no_model_and_no_template_returns_safe_503(tmp_path, monkeypatch):
    setup_demo(tmp_path, monkeypatch)
    with TestClient(app) as client:
        token = client.post("/demo/token", json={"persona": "analyst_a"}).json()["access_token"]
        response = client.post(
            "/ask",
            json={"question": "What is revenue per customer?"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503
    assert response.json()["error_code"] == "DEMO_MODEL_UNAVAILABLE"


def test_demo_limits_apply_character_and_per_ip_and_token_caps(monkeypatch):
    settings = Settings(
        demo_mode=True,
        demo_requests_per_minute=2,
        demo_max_question_length=5,
        auth_jwt_secret=SecretStr(SECRET),
        _env_file=None,
    )
    identity = policy.Identity(user_id="viewer_a", tenant_id="tenant-a", role="viewer")
    calls = []
    monkeypatch.setattr(limits, "_enforce_local_limit", lambda key, limit: calls.append((key, limit)))

    limits.enforce_request_limits(
        identity,
        "short",
        settings,
        client_ip="127.0.0.1",
        access_token="signed-token",
    )
    assert len(calls) == 2
    assert all(limit == 2 for _, limit in calls)
    assert all("127.0.0.1" not in key and "signed-token" not in key for key, _ in calls)

    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as error:
        limits.enforce_request_limits(identity, "too long", settings, client_ip="127.0.0.1", access_token="signed-token")
    assert error.value.status_code == 413
    assert error.value.detail["error_code"] == "QUESTION_LENGTH_LIMIT"


def test_demo_sql_limit_is_enforced_and_smaller_query_limit_is_preserved(tmp_path, monkeypatch):
    settings = setup_demo(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "demo-questions.db") as db:
        db.executemany(
            "INSERT INTO sales(sale_date,region,product,amount,tenant_id) VALUES(?,?,?,?,?)",
            [
                ("2011-04-01", f"Country {number:02d}", "Product", 10.0, "tenant-a")
                for number in range(30)
            ],
        )
    settings.demo_max_rows = 2

    capped, _ = queries.execute_sql(
        "SELECT region, SUM(amount) AS total FROM sales GROUP BY region ORDER BY region",
        "analyst",
        "tenant-a",
        settings,
    )
    one_row, _ = queries.execute_sql(
        "SELECT region, SUM(amount) AS total FROM sales GROUP BY region ORDER BY region LIMIT 1",
        "analyst",
        "tenant-a",
        settings,
    )

    assert len(capped) == 2
    assert len(one_row) == 1
