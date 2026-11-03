"""Smoke-test demo health, personas, and the six expected sample outcomes."""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PERSONAS = ("viewer_a", "analyst_a", "admin_b")
SAMPLES = (
    ("viewer_a", "What was total revenue by month in 2011?", "data"),
    ("analyst_a", "What are the top 5 products by revenue in the United Kingdom?", "data"),
    ("admin_b", "Show revenue by country excluding the United Kingdom.", "data"),
    ("viewer_a", "Delete all sales rows", "blocked"),
    ("viewer_a", "Show tenant B's revenue by country", "denied"),
    ("analyst_a", "Which documents explain how cancellations are handled?", "documents"),
)


def _request(url: str, payload: dict | None = None, token: str | None = None, timeout: float = 10) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"message": "The server returned a non-JSON error."}
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", str(exc))
        raise RuntimeError(f"Could not reach {url}: {reason}") from None
    with response:
        body = response.read().decode("utf-8")
        try:
            return response.status, json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(f"{url} returned a non-JSON response.") from None


def _report(label: str, passed: bool, detail: str = "") -> bool:
    print(f"{'PASS' if passed else 'FAIL'} {label}" + (f": {detail}" if detail else ""))
    return passed


def run(base_url: str, timeout: float = 10) -> int:
    base_url = base_url.rstrip("/")
    passed = True
    try:
        status, health = _request(f"{base_url}/health", timeout=timeout)
        health_ok = (
            status == 200 and health.get("status") == "ok"
            and health.get("demo_mode") is True
            and isinstance(health.get("gemini_key_configured"), bool)
            and isinstance(health.get("chroma_index_exists"), bool)
        )
        passed &= _report("health", health_ok, str(health.get("mode", "unavailable")))
    except RuntimeError as exc:
        passed &= _report("health", False, str(exc))

    tokens = {}
    for persona in PERSONAS:
        try:
            status, result = _request(
                f"{base_url}/demo/token",
                {"persona": persona},
                timeout=timeout,
            )
            token = result.get("access_token")
            token_ok = status == 200 and isinstance(token, str) and bool(token)
            if token_ok:
                tokens[persona] = token
            passed &= _report(f"token {persona}", token_ok)
        except RuntimeError as exc:
            passed &= _report(f"token {persona}", False, str(exc))

    for index, (persona, question, expected) in enumerate(SAMPLES, start=1):
        token = tokens.get(persona)
        if token is None:
            passed &= _report(f"sample {index} ({expected})", False, "persona token unavailable")
            continue
        try:
            status, result = _request(
                f"{base_url}/ask",
                {"question": question},
                token=token,
                timeout=timeout,
            )
            if expected == "denied":
                sample_ok = status == 403 and result.get("error_code") == "TENANT_ACCESS_DENIED"
            elif expected == "blocked":
                sample_ok = (
                    status == 200
                    and not result.get("evidence")
                    and "rejected by the SQL safety checks" in result.get("answer", "")
                )
            else:
                sample_ok = (
                    status == 200
                    and result.get("route") == expected
                    and bool(result.get("evidence"))
                )
            passed &= _report(f"sample {index} ({expected})", sample_ok)
        except RuntimeError as exc:
            passed &= _report(f"sample {index} ({expected})", False, str(exc))
    return 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="Demo API origin, e.g. https://demo.example.com")
    parser.add_argument("--timeout", type=float, default=10, help="Per-request timeout in seconds")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    raise SystemExit(run(args.base_url, args.timeout))


if __name__ == "__main__":
    main()
