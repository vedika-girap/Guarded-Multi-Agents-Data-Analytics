import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("assistant.audit")


def log_request(*, role: str, route: str, latency_ms: float, has_evidence: bool, llm_used: bool) -> None:
    # Do not log question text or evidence payloads, which may contain sensitive data.
    logger.info(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(), "role": role,
        "route": route, "latency_ms": latency_ms, "has_evidence": has_evidence, "llm_used": llm_used,
    }))
