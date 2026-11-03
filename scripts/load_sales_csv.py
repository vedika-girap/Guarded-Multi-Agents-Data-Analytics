"""Idempotently load the prepared Online Retail II CSV into the local SQLite demo."""
import argparse
import csv
import sqlite3
from pathlib import Path

from app.config import DB_PATH, ROOT
from app.ingestion.seed import initialize

DEFAULT_CSV = ROOT / "data" / "processed" / "sales_online_retail.csv"
SOURCE_KEY = "online-retail-ii"
CSV_COLUMNS = {"sale_date", "region", "product", "amount", "tenant_id"}


def load_sales(path: Path = DEFAULT_CSV) -> int:
    if not path.is_file():
        raise FileNotFoundError(f"Prepared sales CSV does not exist: {path}")
    initialize()
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not CSV_COLUMNS.issubset(reader.fieldnames):
            raise ValueError("CSV must include: " + ", ".join(sorted(CSV_COLUMNS)))
        rows = []
        for line_number, row in enumerate(reader, start=2):
            tenant_id = row["tenant_id"].strip()
            if tenant_id not in {"tenant-a", "tenant-b"}:
                raise ValueError(f"CSV line {line_number} has an unsupported tenant_id")
            try:
                amount = round(float(row["amount"]), 2)
            except (TypeError, ValueError):
                raise ValueError(f"CSV line {line_number} has an invalid amount") from None
            if amount <= 0 or not row["sale_date"] or not row["region"] or not row["product"]:
                raise ValueError(f"CSV line {line_number} has an invalid sales record")
            rows.append((row["sale_date"], row["region"], row["product"], amount, tenant_id))

    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS sales_import_rows (
                source_key TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                sale_id INTEGER NOT NULL UNIQUE,
                PRIMARY KEY (source_key, row_number)
            )
        """)
        previous_ids = [
            row[0] for row in db.execute(
                "SELECT sale_id FROM sales_import_rows WHERE source_key=?", (SOURCE_KEY,)
            )
        ]
        for start in range(0, len(previous_ids), 500):
            batch = previous_ids[start:start + 500]
            placeholders = ",".join("?" for _ in batch)
            db.execute(f"DELETE FROM sales WHERE id IN ({placeholders})", batch)
        db.execute("DELETE FROM sales_import_rows WHERE source_key=?", (SOURCE_KEY,))

        for row_number, row in enumerate(rows):
            cursor = db.execute(
                "INSERT INTO sales(sale_date,region,product,amount,tenant_id) VALUES(?,?,?,?,?)",
                row,
            )
            db.execute(
                "INSERT INTO sales_import_rows(source_key,row_number,sale_id) VALUES(?,?,?)",
                (SOURCE_KEY, row_number, cursor.lastrowid),
            )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()
    try:
        count = load_sales(args.input)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print(f"Loaded {count} Online Retail II rows into {DB_PATH}.")


if __name__ == "__main__":
    main()
