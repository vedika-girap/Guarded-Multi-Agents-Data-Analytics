"""Create tenant-scoped sales storage, RLS policy, and approved read view."""
from alembic import op
import sqlalchemy as sa

revision = "0001_sales_rls"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("sale_date", sa.String(10), nullable=False),
        sa.Column("region", sa.String(80), nullable=False),
        sa.Column("product", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    )
    op.create_index("ix_sales_data_tenant_date", "sales_data", ["tenant_id", "sale_date"])
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE ALL ON sales_data FROM PUBLIC, assistant_app")
    op.execute("ALTER TABLE sales_data ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_data FORCE ROW LEVEL SECURITY")
    op.execute("GRANT USAGE, CREATE ON SCHEMA public TO assistant_reader")
    op.execute("GRANT SELECT ON sales_data TO assistant_reader")
    op.execute("""
        CREATE POLICY sales_tenant_select ON sales_data
        FOR SELECT TO assistant_reader
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')
            AND NULLIF(current_setting('app.user_role', true), '') IN ('viewer', 'analyst', 'admin')
        )
    """)
    op.execute("""
        CREATE VIEW sales AS
        SELECT id, sale_date, region, product, amount, tenant_id FROM sales_data
    """)
    op.execute("ALTER VIEW sales OWNER TO assistant_reader")
    op.execute("REVOKE ALL ON sales FROM PUBLIC")
    op.execute("GRANT SELECT ON sales TO assistant_app")
    op.execute("GRANT USAGE ON SCHEMA public TO assistant_app")
    op.execute("REVOKE CREATE ON SCHEMA public FROM assistant_reader")

    sales = sa.table(
        "sales_data",
        sa.column("tenant_id", sa.String), sa.column("sale_date", sa.String),
        sa.column("region", sa.String), sa.column("product", sa.String),
        sa.column("amount", sa.Numeric),
    )
    op.bulk_insert(sales, [
        {"tenant_id": "local-dev-tenant", "sale_date": "2025-01-15", "region": "North", "product": "Atlas", "amount": 1200.0},
        {"tenant_id": "local-dev-tenant", "sale_date": "2025-02-04", "region": "South", "product": "Beacon", "amount": 800.0},
        {"tenant_id": "local-dev-tenant", "sale_date": "2025-02-19", "region": "North", "product": "Cedar", "amount": 450.0},
        {"tenant_id": "local-dev-tenant", "sale_date": "2025-03-08", "region": "West", "product": "Atlas", "amount": 950.0},
        {"tenant_id": "local-dev-tenant", "sale_date": "2025-03-21", "region": "South", "product": "Cedar", "amount": 700.0},
        {"tenant_id": "local-dev-tenant", "sale_date": "2025-04-10", "region": "West", "product": "Beacon", "amount": 1100.0},
    ])


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS sales")
    op.execute("DROP POLICY IF EXISTS sales_tenant_select ON sales_data")
    op.drop_index("ix_sales_data_tenant_date", table_name="sales_data")
    op.drop_table("sales_data")
