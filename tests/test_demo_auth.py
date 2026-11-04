from datetime import datetime, timedelta, timezone
import sqlite3

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import main as main_module
from app.api import routes
from app.auth import limits, policy
from app.config import Settings
from app.graph import llm
from app.ingestion import seed
from app.retrieval import search
from app.sql import queries
from app.main import app

SECRET = "demo-test-secret-that-is-at-least-thirty-two-bytes"


def demo_settings(**overrides):
    values = {
        "environment": "development",
        "auth_mode": "dev",
        "demo_mode": True,
        "auth_jwt_secret": SecretStr(SECRET),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def configure_demo(tmp_path, monkeypatch, settings):
    db_path = tmp_path / "demo-auth.db"
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(search, "DB_PATH", db_path)
    monkeypatch.setattr(search, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(policy, "get_settings", lambda: settings)
    monkeypatch.setattr(limits, "get_settings", lambda: settings)
    monkeypatch.setattr(queries, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "enabled", lambda: False)
    monkeypatch.setattr(main_module, "validate_runtime_settings", lambda: settings)
    return db_path


@pytest.mark.parametrize(
    ("persona", "role", "tenant"),
    [("viewer_a", "viewer", "tenant-a"), ("analyst_a", "analyst", "tenant-a"), ("admin_b", "admin", "tenant-b")],
)
def test_demo_token_issues_only_fixed_personas(tmp_path, monkeypatch, persona, role, tenant):
    settings = demo_settings()
    configure_demo(tmp_path, monkeypatch, settings)
    with TestClient(app) as client:
        response = client.post("/demo/token", json={"persona": persona})

    assert response.status_code == 200
    result = response.json()
    claims = jwt.decode(
        result["access_token"],
        SECRET,
        algorithms=["HS256"],
        audience=policy.DEMO_JWT_AUDIENCE,
        issuer=policy.DEMO_JWT_ISSUER,
    )
    assert result["expires_in"] == 1800
    assert claims["role"] == role
    assert claims["tenant_id"] == tenant


def test_demo_token_rejects_unknown_persona_and_is_hidden_when_disabled(tmp_path, monkeypatch):
    settings = demo_settings()
    configure_demo(tmp_path, monkeypatch, settings)
    with TestClient(app) as client:
        invalid = client.post("/demo/token", json={"persona": "superuser"})
        monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
        disabled = client.post("/demo/token", json={"persona": "viewer_a"})

    assert invalid.status_code == 400
    assert disabled.status_code == 404


def test_invalid_and_expired_demo_tokens_are_rejected(tmp_path, monkeypatch):
    settings = demo_settings()
    configure_demo(tmp_path, monkeypatch, settings)
    expired = jwt.encode(
        {
            "sub": "viewer_a",
            "tenant_id": "tenant-a",
            "role": "viewer",
            "iss": policy.DEMO_JWT_ISSUER,
            "aud": policy.DEMO_JWT_AUDIENCE,
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        SECRET,
        algorithm="HS256",
    )
    for token, expected in [("not-a-token", "INVALID_TOKEN"), (expired, "TOKEN_EXPIRED")]:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            policy.resolve_identity(f"Bearer {token}", settings)
        assert error.value.status_code == 401
        assert error.value.detail["error_code"] == expected


def test_demo_mode_rejects_signed_tokens_outside_fixed_personas():
    settings = demo_settings()
    token = jwt.encode(
        {
            "sub": "made-up-user",
            "tenant_id": "tenant-a",
            "role": "viewer",
            "iss": policy.DEMO_JWT_ISSUER,
            "aud": policy.DEMO_JWT_AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as error:
        policy.resolve_identity(f"Bearer {token}", settings)
    assert error.value.status_code == 401


def test_demo_bearer_token_enforces_tenant_isolation(tmp_path, monkeypatch):
    settings = demo_settings(database_url=f"sqlite:///{(tmp_path / 'demo-auth.db').as_posix()}")
    db_path = configure_demo(tmp_path, monkeypatch, settings)
    seed.initialize()
    with sqlite3.connect(db_path) as db:
        db.executemany(
            "INSERT INTO sales(sale_date,region,product,amount,tenant_id) VALUES(?,?,?,?,?)",
            [
                ("2025-01-01", "North", "A", 10.0, "tenant-a"),
                ("2025-01-02", "North", "A", 20.0, "tenant-a"),
                ("2025-01-03", "North", "A", 30.0, "tenant-a"),
                ("2025-01-01", "North", "B", 1000.0, "tenant-b"),
                ("2025-01-02", "North", "B", 2000.0, "tenant-b"),
                ("2025-01-03", "North", "B", 3000.0, "tenant-b"),
            ],
        )
    with TestClient(app) as client:
        token = client.post("/demo/token", json={"persona": "viewer_a"}).json()["access_token"]
        response = client.post(
            "/ask",
            json={"question": "What is total sales by region?"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    rows = response.json()["evidence"][0]["rows"]
    assert rows == [{"region": "North", "total_sales": 60.0}]


def test_health_reports_nonsecret_runtime_flags(tmp_path, monkeypatch):
    from app import main as main_module

    settings = demo_settings()
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    (tmp_path / "chroma").mkdir()

    health = main_module.health()

    assert health == {
        "status": "ok",
        "mode": "demo",
        "demo_mode": True,
        "gemini_key_configured": False,
        "chroma_index_exists": False,
    }
