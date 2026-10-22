"""Accounts: users and their sessions, and who ran each survey (the signed-in user and the browser).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def timestamp(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("picture", sa.String(1024), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("subject", name=op.f("uq_users_subject")),
    )

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        timestamp("created_at"),
        timestamp("expires_at"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])

    with op.batch_alter_table("surveys") as batch:
        batch.add_column(sa.Column("user_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("device_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("headline", sa.String(200), nullable=True))
        batch.create_index(batch.f("ix_surveys_user_id"), ["user_id"])
        batch.create_index(batch.f("ix_surveys_device_id"), ["device_id"])
        batch.create_foreign_key(batch.f("fk_surveys_user_id_users"), "users", ["user_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("surveys") as batch:
        batch.drop_constraint(batch.f("fk_surveys_user_id_users"), type_="foreignkey")
        batch.drop_index(batch.f("ix_surveys_device_id"))
        batch.drop_index(batch.f("ix_surveys_user_id"))
        for column in ("headline", "device_id", "user_id"):
            batch.drop_column(column)
    op.drop_table("sessions")
    op.drop_table("users")
