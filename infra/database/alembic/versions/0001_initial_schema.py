"""0001_initial_schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-08-26 20:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    # 1. detection_results
    op.create_table(
        "detection_results",
        sa.Column("result_id", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("module_id", sa.String(length=100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset", sa.String(length=50), nullable=False),
        sa.Column("metric_value", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("anomaly_ratio", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("persistence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", json_type, nullable=False),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index("ix_detection_results_event_id", "detection_results", ["event_id"])
    op.create_index("ix_detection_results_module_id", "detection_results", ["module_id"])
    op.create_index("ix_detection_results_timestamp", "detection_results", ["timestamp"])
    op.create_index("ix_detection_results_asset", "detection_results", ["asset"])
    op.create_index("ix_detection_results_status", "detection_results", ["status"])

    # 2. aggregated_results
    op.create_table(
        "aggregated_results",
        sa.Column("aggregation_id", sa.String(length=255), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset", sa.String(length=50), nullable=False),
        sa.Column("composite_anomaly_score", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("max_anomaly_ratio", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("average_anomaly_ratio", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("module_count", sa.Integer(), nullable=False),
        sa.Column("triggered_modules", json_type, nullable=False),
        sa.Column("correlation_window", json_type, nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.PrimaryKeyConstraint("aggregation_id"),
    )
    op.create_index("ix_aggregated_results_timestamp", "aggregated_results", ["timestamp"])
    op.create_index("ix_aggregated_results_asset", "aggregated_results", ["asset"])
    op.create_index("ix_aggregated_results_priority", "aggregated_results", ["priority"])

    # 3. alerts
    op.create_table(
        "alerts",
        sa.Column("alert_id", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("anomaly_score", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("triggered_modules", json_type, nullable=False),
        sa.Column("details", json_type, nullable=False),
        sa.Column("notification_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("notification_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notification_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index("ix_alerts_event_id", "alerts", ["event_id"])
    op.create_index("ix_alerts_timestamp", "alerts", ["timestamp"])
    op.create_index("ix_alerts_asset", "alerts", ["asset"])
    op.create_index("ix_alerts_priority", "alerts", ["priority"])
    op.create_index("ix_alerts_notification_status", "alerts", ["notification_status"])


    # 4. processed_events
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("alerts")
    op.drop_table("aggregated_results")
    op.drop_table("detection_results")
