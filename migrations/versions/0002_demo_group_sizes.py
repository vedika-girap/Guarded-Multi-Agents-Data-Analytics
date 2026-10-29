"""Expand synthetic sales data so default viewer group suppression is demonstrable."""
from alembic import op
import sqlalchemy as sa

revision = "0002_demo_group_sizes"
down_revision = "0001_sales_rls"
branch_labels = None
depends_on = None

_EXTRA_ROWS = [
    {"tenant_id": "local-dev-tenant", "sale_date": "2025-01-22", "region": "West", "product": "Cedar", "amount": 600.0},
    {"tenant_id": "local-dev-tenant", "sale_date": "2025-01-28", "region": "North", "product": "Atlas", "amount": 650.0},
    {"tenant_id": "local-dev-tenant", "sale_date": "2025-02-26", "region": "South", "product": "Beacon", "amount": 700.0},
    {"tenant_id": "local-dev-tenant", "sale_date": "2025-03-29", "region": "West", "product": "Cedar", "amount": 750.0},
    {"tenant_id": "local-dev-tenant", "sale_date": "2025-04-12", "region": "North", "product": "Atlas", "amount": 900.0},
    {"tenant_id": "local-dev-tenant", "sale_date": "2025-04-20", "region": "South", "product": "Beacon", "amount": 850.0},
]


def upgrade() -> None:
    sales = sa.table(
        "sales_data",
        sa.column("tenant_id", sa.String),
        sa.column("sale_date", sa.String),
        sa.column("region", sa.String),
        sa.column("product", sa.String),
        sa.column("amount", sa.Numeric),
    )
    op.bulk_insert(sales, _EXTRA_ROWS)


def downgrade() -> None:
    for row in _EXTRA_ROWS:
        op.execute(sa.text(
            "DELETE FROM sales_data WHERE tenant_id=:tenant_id AND sale_date=:sale_date "
            "AND region=:region AND product=:product AND amount=:amount"
        ).bindparams(**row))
