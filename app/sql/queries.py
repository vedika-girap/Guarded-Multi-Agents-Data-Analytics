import re
import sqlglot
from sqlglot import exp

from app.config import MAX_ROWS, Settings, get_settings
from app.database import connect_readonly, is_postgresql

# Reviewed SQL templates used when the app runs without an LLM key.
QUERIES = {
    "total_sales": ("SELECT ROUND(SUM(amount), 2) AS total_sales FROM sales", "Total sales"),
    "sales_by_region": ("SELECT region, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY region ORDER BY region", "Sales by region"),
    "sales_by_product": ("SELECT product, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY product ORDER BY product", "Sales by product"),
    "sales_by_month": ("SELECT substr(sale_date,1,7) AS month, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY month ORDER BY month", "Sales by month"),
    "top_sale": ("SELECT sale_date, region, product, amount FROM sales ORDER BY amount DESC LIMIT 1", "Largest sale"),
    "demo_monthly_revenue_2011": (
        "SELECT substr(sale_date,1,7) AS month, ROUND(SUM(amount),2) AS total_sales "
        "FROM sales WHERE sale_date >= '2011-01-01' AND sale_date < '2012-01-01' "
        "GROUP BY 1 ORDER BY 1",
        "2011 revenue by month",
    ),
    "demo_top_products_uk": (
        "SELECT product, ROUND(SUM(amount),2) AS total_sales FROM sales "
        "WHERE region = 'United Kingdom' GROUP BY product ORDER BY SUM(amount) DESC LIMIT 5",
        "Top products in the United Kingdom",
    ),
    "demo_revenue_by_country": (
        "SELECT region AS country, ROUND(SUM(amount),2) AS total_sales FROM sales "
        "WHERE region <> 'United Kingdom' GROUP BY region ORDER BY SUM(amount) DESC LIMIT 100",
        "Revenue by country excluding the United Kingdom",
    ),
}


def select_query(question: str) -> str | None:
    q = question.lower()
    if get_settings().demo_mode:
        if "2011" in q and ("by month" in q or "monthly" in q):
            return "demo_monthly_revenue_2011"
        if "top" in q and "product" in q and "united kingdom" in q:
            return "demo_top_products_uk"
        if ("by country" in q or "per country" in q) and "united kingdom" in q:
            return "demo_revenue_by_country"
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
    # SELECT * would expose internal tenant_id through either backend's sales view/table.
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            return False
    allowed_functions = {"COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "SUBSTR", "SUBSTRING", "AND", "OR", "NOT"}
    if tree.find(exp.Placeholder):
        return False
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


def execute_sql(
    sql: str,
    role: str,
    tenant_id: str = "local-dev-tenant",
    settings: Settings | None = None,
) -> tuple[list[dict], str]:
    """Validate generated SQL, enforce tenant/role policy, and execute read-only."""
    settings = settings or get_settings()
    if not validate_sql(sql):
        raise ValueError("Generated SQL did not pass the read-only schema policy")
    if role == "viewer" and not is_aggregate(sql):
        raise PermissionError("Viewer role can run aggregate queries only")
    tree = sqlglot.parse_one(sql, read="sqlite")
    if role == "viewer":
        # Suppress small cells to reduce the risk of disclosing an individual record.
        minimum = exp.GTE(
            this=exp.Count(this=exp.Star()),
            expression=exp.Literal.number(settings.viewer_min_group_size),
        )
        existing_having = tree.args.get("having")
        if existing_having:
            tree.set("having", exp.Having(this=exp.and_(existing_having.this, minimum)))
        else:
            tree.set("having", exp.Having(this=minimum))
    if not is_postgresql(settings):
        # SQLite has no RLS; add the authenticated tenant predicate in application code.
        tenant_filter = exp.EQ(this=exp.column("tenant_id"), expression=exp.Placeholder())
        existing_where = tree.args.get("where")
        if existing_where:
            tree.set("where", exp.Where(this=exp.and_(existing_where.this, tenant_filter)))
        else:
            tree.set("where", exp.Where(this=tenant_filter))
    # Enforce the cap even if the model requested a larger LIMIT.
    row_limit = min(MAX_ROWS, settings.demo_max_rows) if settings.demo_mode else MAX_ROWS
    if settings.demo_mode:
        existing_limit = tree.args.get("limit")
        if existing_limit and isinstance(existing_limit.expression, exp.Literal):
            requested_limit = existing_limit.expression.this
            if existing_limit.expression.is_int and requested_limit.isdecimal():
                row_limit = min(row_limit, int(requested_limit))
    tree = tree.limit(row_limit)
    dialect = "postgres" if is_postgresql(settings) else "sqlite"
    safe_sql = tree.sql(dialect=dialect)
    with connect_readonly(tenant_id, role, settings) as db:
        if is_postgresql(settings):
            rows = db.execute(safe_sql).fetchmany(row_limit)
        else:
            rows = db.execute(safe_sql, (tenant_id,)).fetchmany(row_limit)
    return [dict(row) for row in rows], safe_sql


def execute(query_key: str, row_level: bool = True) -> tuple[list[dict], str]:
    if query_key not in QUERIES:
        raise ValueError("Query is not in the approved query catalog")
    sql, label = QUERIES[query_key]
    role = "analyst" if row_level else "viewer"
    rows, _ = execute_sql(sql, role)
    return rows, label
