"""Surveys and design sheets, and the tables for launch kits and pledges.

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def timestamp(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "surveys",
        sa.Column("id", sa.String(32), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(16), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_surveys")),
    )
    op.create_index(op.f("ix_surveys_created_at"), "surveys", ["created_at"])

    op.create_table(
        "designs",
        sa.Column("survey_id", sa.String(32), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("sheet", sa.JSON(), nullable=False),
        timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["survey_id"], ["surveys.id"], name=op.f("fk_designs_survey_id_surveys"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("survey_id", "idx", name=op.f("pk_designs")),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("survey_id", sa.String(32), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("capture_id", sa.String(64), nullable=True),
        sa.Column("payer_id", sa.String(64), nullable=True),
        sa.Column("environment", sa.String(8), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.ForeignKeyConstraint(["survey_id"], ["surveys.id"], name=op.f("fk_orders_survey_id_surveys")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_index(op.f("ix_orders_survey_id"), "orders", ["survey_id"])
    op.create_index(op.f("ix_orders_status"), "orders", ["status"])

    op.create_table(
        "kits",
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("survey_id", sa.String(32), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_kits_order_id_orders")),
        sa.ForeignKeyConstraint(["survey_id"], ["surveys.id"], name=op.f("fk_kits_survey_id_surveys")),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_kits")),
        sa.UniqueConstraint("order_id", name=op.f("uq_kits_order_id")),
    )
    op.create_index(op.f("ix_kits_survey_id"), "kits", ["survey_id"])
    op.create_index(op.f("ix_kits_status"), "kits", ["status"])

    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("survey_id", sa.String(32), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("owner_token_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("offer", sa.JSON(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("goal_count", sa.Integer(), nullable=False),
        timestamp("deadline"),
        sa.Column("status", sa.String(16), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.ForeignKeyConstraint(["survey_id"], ["surveys.id"], name=op.f("fk_campaigns_survey_id_surveys")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_index(op.f("ix_campaigns_survey_id"), "campaigns", ["survey_id"])
    op.create_index(op.f("ix_campaigns_status"), "campaigns", ["status"])

    op.create_table(
        "pledges",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("campaign_id", sa.String(32), nullable=False),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("authorization_id", sa.String(64), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payer_id", sa.String(64), nullable=True),
        timestamp("created_at"),
        timestamp("authorized_at", nullable=True),
        timestamp("expires_at", nullable=True),
        timestamp("captured_at", nullable=True),
        timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], name=op.f("fk_pledges_campaign_id_campaigns"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pledges")),
        sa.UniqueConstraint("order_id", name=op.f("uq_pledges_order_id")),
    )
    op.create_index(op.f("ix_pledges_campaign_id"), "pledges", ["campaign_id"])
    op.create_index(op.f("ix_pledges_status"), "pledges", ["status"])

    op.create_table(
        "paypal_events",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        timestamp("received_at"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paypal_events")),
    )


def downgrade() -> None:
    for table in ("paypal_events", "pledges", "campaigns", "kits", "orders", "designs", "surveys"):
        op.drop_table(table)
