"""0002_module_configs

Revision ID: 0002_module_configs
Revises: 0001_initial_schema
Create Date: 2026-08-31 16:00:00.000000

"""
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_module_configs"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    module_configs = op.create_table(
        "module_configs",
        sa.Column("module_id", sa.String(length=100), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("reference_price_mode", sa.String(length=20), nullable=False, server_default="AVERAGE"),
        sa.Column("max_price_ratio", sa.Numeric(precision=10, scale=2), nullable=False, server_default="2.00"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("module_id"),
    )

    # Seed initial rows for 4 MVP modules
    now = datetime.now(UTC)
    op.bulk_insert(
        module_configs,
        [
            {
                "module_id": "futures-futures-spread",
                "threshold": Decimal("4.0000000000"),
                "reference_price_mode": "AVERAGE",
                "max_price_ratio": Decimal("2.00"),
                "status": "active",
                "updated_at": now,
            },
            {
                "module_id": "spot-futures-spread",
                "threshold": Decimal("4.0000000000"),
                "reference_price_mode": "AVERAGE",
                "max_price_ratio": Decimal("2.00"),
                "status": "active",
                "updated_at": now,
            },
            {
                "module_id": "dex-futures-spread",
                "threshold": Decimal("4.0000000000"),
                "reference_price_mode": "AVERAGE",
                "max_price_ratio": Decimal("2.00"),
                "status": "active",
                "updated_at": now,
            },
            {
                "module_id": "funding-spread",
                "threshold": Decimal("0.0100000000"),
                "reference_price_mode": "AVERAGE",
                "max_price_ratio": Decimal("2.00"),
                "status": "active",
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("module_configs")
