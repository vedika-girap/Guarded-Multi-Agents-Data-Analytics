import pytest

from app.evaluation import run as evaluation
from app.ingestion import seed
from app.retrieval import search


def test_percentile_uses_nearest_rank():
    assert evaluation.percentile([50, 10, 40, 20, 30], 0.50) == 30
    assert evaluation.percentile([50, 10, 40, 20, 30], 0.95) == 50


@pytest.mark.parametrize("quantile", [0, -0.1, 1.1])
def test_percentile_rejects_invalid_quantiles(quantile):
    with pytest.raises(ValueError):
        evaluation.percentile([1, 2], quantile)


def test_offline_evaluation_reports_measured_quality_safety_and_latency(tmp_path, monkeypatch):
    db_path = tmp_path / "evaluation.db"
    monkeypatch.setattr(evaluation, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(search, "DB_PATH", db_path)

    report = evaluation.run(iterations=1)

    assert report["retrieval"]["hit_rate_at_3"] == 1.0
    assert report["workflow"]["success_rate"] == 1.0
    assert report["sql_safety"]["rejection_rate"] == 1.0
    assert report["authorization"]["pass_rate"] == 1.0
    assert report["latency_ms"]["samples"] == 2
    assert report["latency_ms"]["p50"] >= 0
    assert report["latency_ms"]["p95"] >= report["latency_ms"]["p50"]
    assert report["groundedness"]["status"] == "not_measured"
