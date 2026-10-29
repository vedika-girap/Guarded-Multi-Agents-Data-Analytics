import logging

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app
from app import main as main_module
from app.api import routes
from app.auth import limits, policy
from app.config import Settings
from app.database import DatabaseQueryTimeout
from app.graph import llm, workflow
from app.ingestion import seed
from app.observability.logging import log_request
from app.retrieval import search


@pytest.mark.parametrize(
    ("status_code", "category"),
    [(401, "authentication"), (429, "rate_limited"), (503, "provider_unavailable"), (400, "request_rejected")],
)
def test_gemini_error_status_is_normalized(status_code, category):
    error = type("FakeAPIError", (Exception,), {"code": status_code})("secret provider details")
    normalized = llm._normalize_provider_error(error)

    assert normalized.category == category
    assert normalized.status_code == status_code
    assert "secret" not in str(normalized)


def test_structured_call_wraps_provider_exception_without_exposing_details(monkeypatch):
    class FakeInteractions:
        def create(self, **kwargs):
            raise type("FakeAPIError", (Exception,), {"code": 429})("private response body")

    class FakeClient:
        interactions = FakeInteractions()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    with pytest.raises(llm.GeminiProviderError) as raised:
        llm.structured("route", {"required": []}, "instructions", "input")

    assert raised.value.category == "rate_limited"
    assert "private response body" not in str(raised.value)


def test_structured_output_is_checked_against_schema():
    schema = {
        "type": "object",
        "properties": {"route": {"type": "string", "enum": ["data", "documents"]}},
        "required": ["route"],
        "additionalProperties": False,
    }

    assert llm._matches_schema({"route": "data"}, schema)
    assert not llm._matches_schema({"route": "unsupported"}, schema)
    assert not llm._matches_schema({"route": 7}, schema)
    assert not llm._matches_schema({"route": "data", "extra": "value"}, schema)


def test_workflow_records_node_timings_and_safe_provider_fallback(monkeypatch, caplog):
    seed.initialize()
    monkeypatch.setattr(llm, "enabled", lambda: True)

    def provider_timeout(*args, **kwargs):
        raise llm.GeminiProviderError("timeout")

    monkeypatch.setattr(llm, "structured", provider_timeout)

    with caplog.at_level(logging.WARNING, logger="app.graph.workflow"):
        result = workflow.ask("What does the fiscal year mean?", "viewer", request_id="trace-123")

    assert result["model_status"] == "degraded"
    assert result["provider_failures"] == ["timeout"]
    assert result["node_timings_ms"]["discover"] >= 0
    assert result["node_timings_ms"]["retrieve"] >= 0
    assert result["node_timings_ms"]["answer"] >= 0
    assert any("timed out" in item for item in result["limitations"])
    assert "trace-123" in caplog.text


def test_request_log_has_timings_and_no_question_content(caplog):
    with caplog.at_level(logging.INFO, logger="assistant.audit"):
        log_request(
            request_id="request-123", role="viewer", route="documents", latency_ms=12.5,
            has_evidence=True, llm_used=False, model_status="disabled",
            node_timings_ms={"retrieve": 4.1}, provider_failures=[],
        )

    assert "request-123" in caplog.text
    assert "node_timings_ms" in caplog.text
    assert "the user's secret question" not in caplog.text


def test_ask_api_returns_timing_and_model_status(tmp_path, monkeypatch):
    settings = Settings(_env_file=None)
    db_path = tmp_path / "api-test.db"
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(search, "DB_PATH", db_path)
    monkeypatch.setattr(search, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "validate_runtime_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(limits, "get_settings", lambda: settings)
    monkeypatch.setattr(policy, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "enabled", lambda: False)
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "What does the fiscal year mean?"})
        sales_response = client.post("/ask", json={"question": "What are total sales by region?"})

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    payload = response.json()
    assert payload["model_status"] == "disabled"
    assert payload["node_timings_ms"]["discover"] >= 0
    assert payload["node_timings_ms"]["retrieve"] >= 0

    assert sales_response.status_code == 200
    sales_payload = sales_response.json()
    assert sales_payload["route"] == "data"
    assert len(sales_payload["evidence"][0]["rows"]) == 3


def test_database_timeout_is_not_misreported_as_bad_sql(monkeypatch):
    def timeout(*args, **kwargs):
        raise DatabaseQueryTimeout("internal detail")

    monkeypatch.setattr(workflow, "execute_sql", timeout)
    with pytest.raises(HTTPException) as raised:
        workflow.run_sql({
            "route": "data", "sql": "SELECT SUM(amount) FROM sales", "role": "analyst",
            "tenant_id": "tenant-a",
        })

    assert raised.value.status_code == 504
    assert raised.value.detail["error_code"] == "DATABASE_QUERY_TIMEOUT"
