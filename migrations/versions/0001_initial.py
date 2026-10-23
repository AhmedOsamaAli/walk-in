"""Surveys and their design sheets, and the launch kits made for their concepts.

Revision ID: 0001
Revises:
Create Date: 2026-10-22

A finished survey's state is stored as zlib-compressed JSON (app.db.surveys). A kit goes with its survey.
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
        sa.Column("state", sa.LargeBinary(), nullable=True),
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
        "kits",
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("survey_id", sa.String(32), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["survey_id"], ["surveys.id"], name=op.f("fk_kits_survey_id_surveys"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token", name=op.f("pk_kits")),
        sa.UniqueConstraint("survey_id", "idx", name=op.f("uq_kits_survey_id")),
    )


def downgrade() -> None:
    for table in ("kits", "designs", "surveys"):
        op.drop_table(table)
