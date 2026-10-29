import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("assistant.audit")


def log_request(
    *,
    request_id: str,
    role: str,
    route: str,
    latency_ms: float,
    has_evidence: bool,
    llm_used: bool,
    model_status: str,
    node_timings_ms: dict[str, float],
    provider_failures: list[str],
) -> None:
    # Do not log question text, SQL results, evidence, or provider exception details.
    logger.info(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "role": role,
        "route": route,
        "latency_ms": latency_ms,
        "has_evidence": has_evidence,
        "llm_used": llm_used,
        "model_status": model_status,
        "provider_failures": provider_failures,
        "node_timings_ms": node_timings_ms,
    }))
