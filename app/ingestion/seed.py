import sqlite3

from app.config import DATA_DIR, DB_PATH

DOCUMENTS = [
    ("sales_policy", "Sales reporting guide", "Revenue is reported in USD. The fiscal year runs from January through December. Returns are excluded from net sales."),
    ("region_notes", "Region definitions", "North includes the northern territory accounts. South includes southern territory accounts. Region is assigned from the account billing address."),
    ("product_notes", "Product catalog notes", "The sample catalog contains Atlas, Beacon, and Cedar products. Product names in sales records are the approved reporting labels."),
]


def initialize() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY, sale_date TEXT NOT NULL, region TEXT NOT NULL,
                product TEXT NOT NULL, amount REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(
                doc_id UNINDEXED, title, body
            );
        """)
        if db.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0:
            db.executemany("INSERT INTO sales(sale_date,region,product,amount) VALUES(?,?,?,?)", [
                ("2025-01-15", "North", "Atlas", 1200.0),
                ("2025-02-04", "South", "Beacon", 800.0),
                ("2025-02-19", "North", "Cedar", 450.0),
                ("2025-03-08", "West", "Atlas", 950.0),
                ("2025-03-21", "South", "Cedar", 700.0),
                ("2025-04-10", "West", "Beacon", 1100.0),
            ])
        if db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0:
            db.executemany("INSERT INTO documents(doc_id,title,body) VALUES(?,?,?)", DOCUMENTS)
