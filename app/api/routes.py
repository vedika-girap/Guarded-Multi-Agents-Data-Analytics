from time import perf_counter

from fastapi import APIRouter, Depends, Request

from app.api.models import AskRequest, AskResponse
from app.auth.limits import enforce_request_limits
from app.auth.policy import Identity, current_identity
from app.config import get_settings
from app.graph.workflow import ask
from app.observability.logging import log_request

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest, raw_request: Request, identity: Identity = Depends(current_identity)) -> AskResponse:
    enforce_request_limits(identity, request.question, get_settings())
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
