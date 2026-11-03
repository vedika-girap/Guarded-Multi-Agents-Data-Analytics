"""Prepare UCI Online Retail II workbook rows for the demo sales schema."""
import argparse
import logging
from pathlib import Path

import pandas as pd

from app.config import ROOT

LOGGER = logging.getLogger("prepare_online_retail")
DEFAULT_INPUT = ROOT / "data" / "raw" / "online_retail_II.xlsx"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "sales_online_retail.csv"
DEFAULT_MAX_ROWS = 50_000
RANDOM_SEED = 42
SHEETS = ("Year 2009-2010", "Year 2010-2011")
REQUIRED_COLUMNS = {
    "Invoice", "StockCode", "Description", "Quantity",
    "InvoiceDate", "Price", "Country",
}


def _drop_rows(frame: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
    dropped = int(mask.sum())
    LOGGER.info("Dropped %s rows: %s", dropped, reason)
    return frame.loc[~mask].copy()


def prepare(input_path: Path, output_path: Path, max_rows: int = DEFAULT_MAX_ROWS) -> int:
    if max_rows < 1:
        raise ValueError("--max-rows must be greater than zero")

    sheets = pd.read_excel(input_path, sheet_name=list(SHEETS), engine="openpyxl")
    frame = pd.concat([sheets[name] for name in SHEETS], ignore_index=True)
    missing_columns = REQUIRED_COLUMNS - set(frame.columns)
    if missing_columns:
        raise ValueError("Workbook is missing required columns: " + ", ".join(sorted(missing_columns)))

    # CHANGE HERE: The source-to-sales mapping is intentionally limited to the
    # app's existing columns; customer identifiers and product codes are not imported.
    frame = frame.drop(columns=["Customer ID"], errors="ignore")
    invoice = frame["Invoice"].astype("string").str.strip().str.upper()
    frame = _drop_rows(frame, invoice.str.startswith("C", na=False), "cancelled invoices")
    frame = _drop_rows(frame, frame["Description"].isna(), "missing descriptions")

    quantity = pd.to_numeric(frame["Quantity"], errors="coerce")
    frame = _drop_rows(frame, quantity.isna() | (quantity <= 0), "missing or nonpositive quantities")
    frame["Quantity"] = quantity.loc[frame.index]
    price = pd.to_numeric(frame["Price"], errors="coerce")
    frame = _drop_rows(frame, price.isna() | (price <= 0), "missing or nonpositive prices")
    frame["Price"] = price.loc[frame.index]

    dates = pd.to_datetime(frame["InvoiceDate"], errors="coerce")
    frame = _drop_rows(frame, dates.isna(), "invalid invoice dates")
    frame["sale_date"] = dates.loc[frame.index].dt.strftime("%Y-%m-%d")
    frame["region"] = frame["Country"].astype("string").str.strip()
    frame = _drop_rows(frame, frame["region"].isna() | frame["region"].eq(""), "missing countries")
    frame["product"] = frame["Description"].astype("string").str.strip()
    frame["amount"] = (frame["Quantity"] * frame["Price"]).round(2)
    frame["tenant_id"] = frame["region"].map(
        lambda country: "tenant-a" if country == "United Kingdom" else "tenant-b"
    )

    daily = (
        frame.groupby(["sale_date", "region", "product", "tenant_id"], as_index=False)["amount"]
        .sum()
    )
    daily["amount"] = daily["amount"].round(2)
    if len(daily) > max_rows:
        daily = daily.sample(n=max_rows, random_state=RANDOM_SEED)
    daily = daily.sort_values(["sale_date", "region", "product"]).reset_index(drop=True)
    output = daily[["sale_date", "region", "product", "amount", "tenant_id"]]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    LOGGER.info("Wrote %s daily product rows to %s", len(output), output_path)
    return len(output)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    args = parser.parse_args()
    try:
        prepare(args.input, args.output, args.max_rows)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
