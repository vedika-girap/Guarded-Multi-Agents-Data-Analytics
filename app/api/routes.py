from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from time import perf_counter

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import FileResponse

from app.api.models import AskRequest, AskResponse
from app.auth.limits import enforce_request_limits
from app.auth.policy import (
    DEMO_JWT_AUDIENCE,
    DEMO_JWT_ISSUER,
    DEMO_PERSONAS,
    Identity,
    current_identity,
)
from app.config import get_settings
from app.graph.workflow import ask
from app.observability.logging import log_request

router = APIRouter()
DEMO_PAGE = Path(__file__).resolve().parents[1] / "static" / "demo.html"


class DemoTokenRequest(BaseModel):
    persona: str


@router.post("/demo/token")
def issue_demo_token(request: DemoTokenRequest) -> dict:
    settings = get_settings()
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail={"error_code": "NOT_FOUND", "message": "Not found."})
    persona = DEMO_PERSONAS.get(request.persona)
    if persona is None:
        raise HTTPException(status_code=400, detail={"error_code": "INVALID_PERSONA", "message": "Choose a supported demo persona."})
    if settings.auth_jwt_secret is None:
        raise HTTPException(status_code=503, detail={"error_code": "AUTH_CONFIGURATION_ERROR", "message": "Demo authentication is not configured."})

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)
    # CHANGE HERE: Keep this allowlist limited to the three non-sensitive demo personas.
    token = jwt.encode(
        {
            "sub": request.persona,
            "tenant_id": persona["tenant_id"],
            "role": persona["role"],
            "iss": DEMO_JWT_ISSUER,
            "aud": DEMO_JWT_AUDIENCE,
            "iat": now,
            "exp": expires_at,
        },
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 1800,
        "tenant_id": persona["tenant_id"],
        "role": persona["role"],
    }


@router.get("/demo", include_in_schema=False)
def demo_page() -> FileResponse:
    if not get_settings().demo_mode:
        raise HTTPException(status_code=404, detail={"error_code": "NOT_FOUND", "message": "Not found."})
    return FileResponse(DEMO_PAGE, media_type="text/html")


@router.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest, raw_request: Request, identity: Identity = Depends(current_identity)) -> AskResponse:
    settings = get_settings()
    if settings.demo_mode:
        tenant_match = re.search(r"\btenant\s+([ab])\b", request.question, flags=re.IGNORECASE)
        expected_tenant = "tenant-a" if tenant_match and tenant_match.group(1).lower() == "a" else "tenant-b"
        if tenant_match and expected_tenant != identity.tenant_id:
            raise HTTPException(
                status_code=403,
                detail={"error_code": "TENANT_ACCESS_DENIED", "message": "The requested tenant is not available to this identity."},
            )
    authorization = raw_request.headers.get("authorization", "")
    access_token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else None
    enforce_request_limits(
        identity,
        request.question,
        settings,
        client_ip=raw_request.client.host if raw_request.client else None,
        access_token=access_token,
    )
    started = perf_counter()
    request_id = getattr(raw_request.state, "request_id", "unknown")
    result = ask(request.question, identity.role, identity.tenant_id, request_id)
    latency_ms = round((perf_counter() - started) * 1000, 2)
    log_request(
        request_id=request_id,
        role=identity.role,
        route=result["route"],
        latency_ms=latency_ms,
        has_evidence=bool(result["evidence"]),
        llm_used=result["llm_used"],
        model_status=result["model_status"],
        node_timings_ms=result["node_timings_ms"],
        provider_failures=result["provider_failures"],
    )
    return AskResponse(**result, latency_ms=latency_ms)
