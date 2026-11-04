import sqlite3

import pandas as pd
import pytest

from app.ingestion import seed
from scripts import load_sales_csv, prepare_online_retail


def test_prepare_online_retail_filters_maps_and_deterministically_caps(tmp_path):
    rows = [
        ("10001", "A1", "Tea", 2, "2011-01-01", 3.50, 123, "United Kingdom"),
        ("10002", "B2", "Coffee", 1, "2011-01-02", 4.00, 456, "France"),
        ("C10003", "C3", "Cancelled", 1, "2011-01-03", 2.00, 789, "United Kingdom"),
        ("10004", "D4", None, 1, "2011-01-04", 2.00, 111, "United Kingdom"),
        ("10005", "E5", "Zero quantity", 0, "2011-01-05", 2.00, 112, "United Kingdom"),
        ("10006", "F6", "Zero price", 1, "2011-01-06", 0, 113, "France"),
    ]
    columns = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
    workbook = tmp_path / "input.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(rows, columns=columns).to_excel(writer, sheet_name="Year 2009-2010", index=False)
        pd.DataFrame(rows[:2], columns=columns).to_excel(writer, sheet_name="Year 2010-2011", index=False)

    output = tmp_path / "prepared.csv"
    count = prepare_online_retail.prepare(workbook, output, max_rows=1)
    result = pd.read_csv(output)

    assert count == len(result) == 1
    assert list(result.columns) == ["sale_date", "region", "product", "amount", "tenant_id"]
    assert result.iloc[0]["tenant_id"] in {"tenant-a", "tenant-b"}
    assert "Customer ID" not in result.columns
    assert result.iloc[0]["amount"] in {14.0, 8.0}


def test_prepare_rejects_nonpositive_max_rows():
    with pytest.raises(ValueError, match="max-rows"):
        prepare_online_retail.prepare(None, None, max_rows=0)


def test_load_sales_csv_is_idempotent_and_preserves_seed_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "sales.db"
    monkeypatch.setattr(seed, "DB_PATH", db_path)
    monkeypatch.setattr(seed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(load_sales_csv, "DB_PATH", db_path)
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "sale_date,region,product,amount,tenant_id\n"
        "2011-01-01,United Kingdom,Tea,7.00,tenant-a\n"
        "2011-01-02,France,Coffee,4.00,tenant-b\n",
        encoding="utf-8",
    )

    assert load_sales_csv.load_sales(csv_path) == 2
    assert load_sales_csv.load_sales(csv_path) == 2
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM sales WHERE tenant_id='local-dev-tenant'").fetchone()[0] == 12
        assert db.execute("SELECT COUNT(*) FROM sales WHERE tenant_id IN ('tenant-a','tenant-b')").fetchone()[0] == 2


def test_load_sales_csv_requires_prepared_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        load_sales_csv.load_sales(tmp_path / "missing.csv")
