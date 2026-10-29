"""Repeatable offline quality, safety, and latency evaluation for the demo."""
import argparse
import json
import math
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from app.config import DB_PATH, Settings
from app.graph.workflow import ask
from app.ingestion.seed import initialize
from app.retrieval.search import search_documents
from app.sql.queries import execute_sql, validate_sql

RETRIEVAL_CASES = [
    ("How is the fiscal year defined?", "sales_policy"),
    ("What does North include?", "region_notes"),
    ("Which products are in the sample catalog?", "product_notes"),
]
REJECT_CASES = [
    "DELETE FROM sales",
    "SELECT * FROM sales; DROP TABLE sales",
    "SELECT * FROM users",
    "SELECT tenant_id FROM sales",
]
QUESTION_CASES = [
    ("What does the fiscal year mean?", "documents"),
    ("What are total sales by region?", "data"),
]


def percentile(values: list[float], quantile: float) -> float:
    """Nearest-rank percentile; deterministic for small evaluation samples."""
    if not values:
        raise ValueError("At least one measurement is required")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be greater than 0 and at most 1")
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(quantile * len(ordered)) - 1)], 2)


def _create_security_fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        with db:
            db.execute(
                "CREATE TABLE sales (id INTEGER PRIMARY KEY, sale_date TEXT NOT NULL, "
                "region TEXT NOT NULL, product TEXT NOT NULL, amount REAL NOT NULL, tenant_id TEXT NOT NULL)"
            )
            db.executemany(
                "INSERT INTO sales(sale_date,region,product,amount,tenant_id) VALUES(?,?,?,?,?)",
                [
                    ("2025-01-01", "North", "Atlas", 10.0, "tenant-a"),
                    ("2025-01-02", "North", "Atlas", 20.0, "tenant-a"),
                    ("2025-01-03", "North", "Atlas", 30.0, "tenant-a"),
                    ("2025-01-04", "South", "Beacon", 40.0, "tenant-a"),
                    ("2025-01-05", "South", "Beacon", 50.0, "tenant-a"),
                    ("2025-01-01", "North", "Atlas", 1000.0, "tenant-b"),
                    ("2025-01-02", "North", "Atlas", 2000.0, "tenant-b"),
                    ("2025-01-03", "North", "Atlas", 3000.0, "tenant-b"),
                ],
            )


def _security_metrics() -> dict:
    with tempfile.TemporaryDirectory(prefix="analytics-eval-") as directory:
        path = Path(directory) / "security.db"
        _create_security_fixture(path)
        settings = Settings(
            environment="development",
            auth_mode="dev",
            database_url=f"sqlite:///{path.as_posix()}",
            _env_file=None,
        )
        checks = {}
        own_rows, _ = execute_sql(
            "SELECT SUM(amount) AS total FROM sales", "analyst", "tenant-a", settings,
        )
        other_rows, _ = execute_sql(
            "SELECT SUM(amount) AS total FROM sales", "analyst", "tenant-b", settings,
        )
        checks["tenant_isolation"] = own_rows == [{"total": 150.0}] and other_rows == [{"total": 6000.0}]

        try:
            execute_sql("SELECT id, amount FROM sales", "viewer", "tenant-a", settings)
            checks["viewer_row_access_denied"] = False
        except PermissionError:
            checks["viewer_row_access_denied"] = True

        grouped, _ = execute_sql(
            "SELECT region, COUNT(*) AS records FROM sales GROUP BY region ORDER BY region",
            "viewer", "tenant-a", settings,
        )
        checks["small_groups_suppressed"] = grouped == [{"region": "North", "records": 3}]

    passed = sum(checks.values())
    return {"checks": checks, "passed": passed, "total": len(checks), "pass_rate": round(passed / len(checks), 3)}


def run(iterations: int = 5) -> dict:
    if iterations < 1 or iterations > 100:
        raise ValueError("iterations must be between 1 and 100")
    initialize()
    settings = Settings(
        environment="development",
        auth_mode="dev",
        database_url=f"sqlite:///{DB_PATH.as_posix()}",
        _env_file=None,
    )

    with patch("app.retrieval.search.get_settings", return_value=settings):
        hits = sum(
            any(doc["source_id"] == expected for doc in search_documents(question))
            for question, expected in RETRIEVAL_CASES
        )
    rejected = sum(not validate_sql(sql) for sql in REJECT_CASES)

    timings_ms = []
    question_results = []
    # Keep the evaluation offline and repeatable even if a developer has a key
    # in .env. Model quality must be measured in a separate, explicit live eval.
    with (
        patch("app.graph.llm.enabled", return_value=False),
        patch("app.retrieval.search.get_settings", return_value=settings),
        patch("app.sql.queries.get_settings", return_value=settings),
    ):
        for question, expected_route in QUESTION_CASES:
            evidence_successes = 0
            for _ in range(iterations):
                started = perf_counter()
                result = ask(question, "viewer", "local-dev-tenant")
                timings_ms.append((perf_counter() - started) * 1000)
                if result["route"] == expected_route and result["evidence"]:
                    evidence_successes += 1
            question_results.append({
                "expected_route": expected_route,
                "runs": iterations,
                "supported_with_evidence": evidence_successes,
                "success_rate": round(evidence_successes / iterations, 3),
            })

    safety = _security_metrics()
    supported = sum(item["supported_with_evidence"] for item in question_results)
    total_questions = iterations * len(QUESTION_CASES)
    return {
        "evaluation_set": {
            "retrieval_cases": len(RETRIEVAL_CASES),
            "workflow_questions": len(QUESTION_CASES),
            "iterations_per_question": iterations,
        },
        "retrieval": {
            "hit_at_3": hits,
            "total": len(RETRIEVAL_CASES),
            "hit_rate_at_3": round(hits / len(RETRIEVAL_CASES), 3),
        },
        "workflow": {
            "supported_with_evidence": supported,
            "total_runs": total_questions,
            "success_rate": round(supported / total_questions, 3),
            "cases": question_results,
        },
        "sql_safety": {
            "disallowed_rejected": rejected,
            "total": len(REJECT_CASES),
            "rejection_rate": round(rejected / len(REJECT_CASES), 3),
        },
        "authorization": safety,
        "latency_ms": {
            "samples": len(timings_ms),
            "p50": percentile(timings_ms, 0.50),
            "p95": percentile(timings_ms, 0.95),
        },
        "groundedness": {
            "status": "not_measured",
            "reason": "This offline evaluation disables Gemini; use a labeled human-reviewed set for live answer groundedness.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic offline project evaluation.")
    parser.add_argument("--iterations", type=int, default=5, help="Runs per workflow question (1-100, default 5)")
    args = parser.parse_args()
    print(json.dumps(run(args.iterations), indent=2))


if __name__ == "__main__":
    main()
