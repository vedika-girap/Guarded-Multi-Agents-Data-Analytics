from app.ingestion.seed import initialize
from app.retrieval.search import search_documents
from app.sql.queries import validate_sql

RETRIEVAL_CASES = [
    ("How is the fiscal year defined?", "sales_policy"),
    ("What does North include?", "region_notes"),
    ("Which products are in the sample catalog?", "product_notes"),
]
REJECT_CASES = ["DELETE FROM sales", "SELECT * FROM sales; DROP TABLE sales", "SELECT * FROM users"]


def main() -> None:
    initialize()
    hits = sum(any(doc["source_id"] == expected for doc in search_documents(q)) for q, expected in RETRIEVAL_CASES)
    rejected = sum(not validate_sql(sql) for sql in REJECT_CASES)
    print(f"Retrieval hit rate@3: {hits}/{len(RETRIEVAL_CASES)} = {hits / len(RETRIEVAL_CASES):.3f}")
    print(f"Disallowed SQL rejected: {rejected}/{len(REJECT_CASES)}")


if __name__ == "__main__":
    main()
