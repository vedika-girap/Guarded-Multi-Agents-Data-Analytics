import sqlite3

from app.config import DATA_DIR, DB_PATH

DOCUMENTS = [
    ("sales_policy", "Sales reporting guide", "Revenue is reported in USD. The fiscal year runs from January through December. Returns are excluded from net sales."),
    ("region_notes", "Region definitions", "North includes the northern territory accounts. South includes southern territory accounts. Region is assigned from the account billing address."),
    ("product_notes", "Product catalog notes", "The sample catalog contains Atlas, Beacon, and Cedar products. Product names in sales records are the approved reporting labels."),
]
ROLE_LEVELS = {"viewer": 0, "analyst": 1, "admin": 2}
BASE_DEMO_SALES = [
    ("2025-01-15", "North", "Atlas", 1200.0, "local-dev-tenant"),
    ("2025-02-04", "South", "Beacon", 800.0, "local-dev-tenant"),
    ("2025-02-19", "North", "Cedar", 450.0, "local-dev-tenant"),
    ("2025-03-08", "West", "Atlas", 950.0, "local-dev-tenant"),
    ("2025-03-21", "South", "Cedar", 700.0, "local-dev-tenant"),
    ("2025-04-10", "West", "Beacon", 1100.0, "local-dev-tenant"),
]
EXTRA_DEMO_SALES = [
    ("2025-01-22", "West", "Cedar", 600.0, "local-dev-tenant"),
    ("2025-01-28", "North", "Atlas", 650.0, "local-dev-tenant"),
    ("2025-02-26", "South", "Beacon", 700.0, "local-dev-tenant"),
    ("2025-03-29", "West", "Cedar", 750.0, "local-dev-tenant"),
    ("2025-04-12", "North", "Atlas", 900.0, "local-dev-tenant"),
    ("2025-04-20", "South", "Beacon", 850.0, "local-dev-tenant"),
]


def initialize() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS document_sources (
                tenant_id TEXT NOT NULL, source_root TEXT NOT NULL,
                source_path TEXT NOT NULL, chunk_index INTEGER NOT NULL,
                doc_id TEXT NOT NULL,
                PRIMARY KEY(tenant_id, source_root, source_path, chunk_index)
            );
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY, sale_date TEXT NOT NULL, region TEXT NOT NULL,
                product TEXT NOT NULL, amount REAL NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'local-dev-tenant'
            );
        """)
        # Upgrade the original demo FTS table with access-control metadata.
        doc_columns = {row[1] for row in db.execute("PRAGMA table_info(documents)")}
        if doc_columns and not {"tenant_id", "min_role", "source_name"}.issubset(doc_columns):
            db.execute("ALTER TABLE documents RENAME TO documents_legacy")
        db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(
            doc_id UNINDEXED, title, body, tenant_id UNINDEXED,
            min_role UNINDEXED, source_name UNINDEXED
        )""")
        if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents_legacy'").fetchone():
            db.execute("""INSERT INTO documents(doc_id,title,body,tenant_id,min_role,source_name)
                SELECT doc_id,title,body,'local-dev-tenant',0,'seed' FROM documents_legacy""")
            db.execute("DROP TABLE documents_legacy")
        # Add the tenant key to an existing Stage 1 demo database without dropping data.
        sales_columns = {row[1] for row in db.execute("PRAGMA table_info(sales)")}
        if "tenant_id" not in sales_columns:
            db.execute("ALTER TABLE sales ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local-dev-tenant'")
        sales = db.execute(
            "SELECT sale_date,region,product,amount,tenant_id FROM sales ORDER BY sale_date,region,product"
        ).fetchall()
        base_sorted = sorted(BASE_DEMO_SALES)
        if not sales:
            db.executemany(
                "INSERT INTO sales(sale_date,region,product,amount,tenant_id) VALUES(?,?,?,?,?)",
                BASE_DEMO_SALES + EXTRA_DEMO_SALES,
            )
        elif [tuple(row) for row in sales] == base_sorted:
            # Upgrade only the exact original synthetic dataset; never add demo
            # rows to a database that contains user-provided records.
            db.executemany(
                "INSERT INTO sales(sale_date,region,product,amount,tenant_id) VALUES(?,?,?,?,?)",
                EXTRA_DEMO_SALES,
            )
        if db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO documents(doc_id,title,body,tenant_id,min_role,source_name) VALUES(?,?,?,?,?,?)",
                [(doc_id, title, body, "local-dev-tenant", ROLE_LEVELS["viewer"], "seed") for doc_id, title, body in DOCUMENTS],
            )
