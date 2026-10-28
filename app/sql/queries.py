import re
import sqlite3

import sqlglot
from sqlglot import exp

from app.config import DB_PATH, MAX_ROWS

# Reviewed SQL templates used when the app runs without an LLM key.
QUERIES = {
    "total_sales": ("SELECT ROUND(SUM(amount), 2) AS total_sales FROM sales", "Total sales"),
    "sales_by_region": ("SELECT region, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY region ORDER BY region", "Sales by region"),
    "sales_by_product": ("SELECT product, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY product ORDER BY product", "Sales by product"),
    "sales_by_month": ("SELECT substr(sale_date,1,7) AS month, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY month ORDER BY month", "Sales by month"),
    "top_sale": ("SELECT sale_date, region, product, amount FROM sales ORDER BY amount DESC LIMIT 1", "Largest sale"),
}


def select_query(question: str) -> str | None:
    q = question.lower()
    if "largest" in q or "highest" in q or "top sale" in q:
        return "top_sale"
    if "by region" in q or "per region" in q:
        return "sales_by_region"
    if "by product" in q or "per product" in q:
        return "sales_by_product"
    if "by month" in q or "monthly" in q or "each month" in q:
        return "sales_by_month"
    if re.search(r"\b(total|sum|overall)\b", q) and re.search(r"\b(sales|revenue)\b", q):
        return "total_sales"
    return None


def validate_sql(sql: str) -> bool:
    """Allow a single simple SELECT over approved sales columns only."""
    if not sql or len(sql) > 2000:
        return False
    try:
        statements = sqlglot.parse(sql, read="sqlite")
    except (sqlglot.errors.ParseError, ValueError):
        return False
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return False
    tree = statements[0]
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1 or (tables[0].name or "").lower() != "sales":
        return False
    if any(tree.find(node) for node in (exp.Join, exp.Subquery, exp.With, exp.Union)):
        return False
    allowed_columns = {"id", "sale_date", "region", "product", "amount"}
    if any(column.name.lower() not in allowed_columns for column in tree.find_all(exp.Column)):
        return False
    allowed_functions = {"COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "SUBSTR", "SUBSTRING"}
    for function in tree.find_all(exp.Func):
        try:
            function_name = function.sql_name().upper()
        except (AttributeError, TypeError):
            return False
        if function_name not in allowed_functions:
            return False
    return True


def is_aggregate(sql: str) -> bool:
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except (sqlglot.errors.ParseError, ValueError):
        return False
    aggregate_names = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
    return any(function.sql_name().upper() in aggregate_names for function in tree.find_all(exp.Func))


def execute_sql(sql: str, role: str) -> tuple[list[dict], str]:
    """Validate generated SQL, enforce role granularity, and run with SQLite read-only."""
    if not validate_sql(sql):
        raise ValueError("Generated SQL did not pass the read-only schema policy")
    if role == "viewer" and not is_aggregate(sql):
        raise PermissionError("Viewer role can run aggregate queries only")
    tree = sqlglot.parse_one(sql, read="sqlite")
    # Enforce the cap even if the model requested a larger LIMIT.
    tree = tree.limit(MAX_ROWS)
    safe_sql = tree.sql(dialect="sqlite")
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as db:
        db.set_progress_handler(lambda: 1, 100_000)
        db.row_factory = sqlite3.Row
        rows = db.execute(safe_sql).fetchmany(MAX_ROWS)
    return [dict(row) for row in rows], safe_sql


def execute(query_key: str, row_level: bool = True) -> tuple[list[dict], str]:
    if query_key not in QUERIES:
        raise ValueError("Query is not in the approved query catalog")
    sql, label = QUERIES[query_key]
    role = "analyst" if row_level else "viewer"
    rows, _ = execute_sql(sql, role)
    return rows, label
