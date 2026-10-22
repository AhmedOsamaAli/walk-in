"""Paid features: who bought each order and kit and who owns each campaign, and what kits, campaigns and pledges need to
be built and settled.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def timestamp(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def owned_by_user(batch, table: str) -> None:
    """Adds user_id, its index and its foreign key to users."""
    batch.add_column(sa.Column("user_id", sa.String(32), nullable=True))
    batch.create_index(batch.f(f"ix_{table}_user_id"), ["user_id"])
    batch.create_foreign_key(batch.f(f"fk_{table}_user_id_users"), "users", ["user_id"], ["id"])


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        owned_by_user(batch, "orders")

    with op.batch_alter_table("kits") as batch:
        owned_by_user(batch, "kits")
        batch.add_column(sa.Column("name", sa.String(200), nullable=True))
        batch.add_column(sa.Column("error", sa.String(500), nullable=True))

    with op.batch_alter_table("campaigns") as batch:
        batch.alter_column("owner_token_hash", existing_type=sa.String(64), nullable=True)
        owned_by_user(batch, "campaigns")
        batch.add_column(sa.Column("kit_token", sa.String(64), nullable=True))
        batch.add_column(timestamp("closed_at", nullable=True))
        batch.add_column(sa.Column("funded", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("report", sa.JSON(), nullable=True))
        batch.create_index(batch.f("ix_campaigns_kit_token"), ["kit_token"])
        batch.create_foreign_key(batch.f("fk_campaigns_kit_token_kits"), "kits", ["kit_token"], ["token"])

    with op.batch_alter_table("pledges") as batch:
        batch.add_column(sa.Column("reauthorization_id", sa.String(64), nullable=True))
        batch.add_column(timestamp("reauthorized_at", nullable=True))
        batch.add_column(sa.Column("capture_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("error", sa.String(64), nullable=True))
        batch.add_column(sa.Column("withdraw_token_hash", sa.String(64), nullable=True))
        batch.create_unique_constraint(batch.f("uq_pledges_withdraw_token_hash"), ["withdraw_token_hash"])


def downgrade() -> None:
    with op.batch_alter_table("pledges") as batch:
        batch.drop_constraint(batch.f("uq_pledges_withdraw_token_hash"), type_="unique")
        for column in ("withdraw_token_hash", "error", "capture_id", "reauthorized_at", "reauthorization_id"):
            batch.drop_column(column)

    # Campaigns started by signed-in owners have no owner token; they keep an empty one.
    op.execute(sa.text("UPDATE campaigns SET owner_token_hash = '' WHERE owner_token_hash IS NULL"))
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_constraint(batch.f("fk_campaigns_kit_token_kits"), type_="foreignkey")
        batch.drop_index(batch.f("ix_campaigns_kit_token"))
        batch.drop_constraint(batch.f("fk_campaigns_user_id_users"), type_="foreignkey")
        batch.drop_index(batch.f("ix_campaigns_user_id"))
        for column in ("report", "funded", "closed_at", "kit_token", "user_id"):
            batch.drop_column(column)
        batch.alter_column("owner_token_hash", existing_type=sa.String(64), nullable=False)

    for table, columns in (("kits", ("error", "name")), ("orders", ())):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(batch.f(f"fk_{table}_user_id_users"), type_="foreignkey")
            batch.drop_index(batch.f(f"ix_{table}_user_id"))
            for column in (*columns, "user_id"):
                batch.drop_column(column)
