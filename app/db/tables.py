"""The database's tables, as SQLAlchemy Core. The migrations in migrations/ create them; keep both in step.

The app writes surveys and their design sheets. Orders, kits, campaigns, pledges and PayPal events are for launch kits
and pledges paid with PayPal: amounts are integer cents, and ids that come from PayPal are PayPal's.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, Dialect, Float, ForeignKey, Integer, MetaData, String, Table
from sqlalchemy.types import TypeDecorator

# Constraint and index names, spelled out in the migrations, so later migrations can find them on every database.
metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """A timezone-aware UTC timestamp on every database; SQLite stores no zone, so its values are marked UTC on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _created() -> Column:
    return Column("created_at", UTCDateTime, nullable=False, default=utcnow)


def _updated() -> Column:
    return Column("updated_at", UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


surveys = Table(
    "surveys", metadata,
    Column("id", String(32), primary_key=True),
    Column("created_at", UTCDateTime, nullable=False, default=utcnow, index=True),
    _updated(),
    Column("status", String(16), nullable=False),  # running | complete | failed
    Column("intent", String(16), nullable=False),  # explore | open | improve
    Column("label", String(200), nullable=False),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("request", JSON, nullable=False),  # the site and the owner's brief, as asked
    Column("events", JSON, nullable=False),  # every event as streamed: [event, data, seconds since the start]
    Column("state", JSON),  # the finished run (app.survey.snapshot), so it can still be designed after a restart
)

designs = Table(
    "designs", metadata,
    Column("survey_id", String(32), ForeignKey("surveys.id", ondelete="CASCADE"), primary_key=True),
    Column("idx", Integer, primary_key=True),  # the concept's position in the survey's concepts
    Column("sheet", JSON, nullable=False),
    _created(),
)

orders = Table(
    "orders", metadata,
    Column("id", String(64), primary_key=True),  # the PayPal order id
    Column("survey_id", String(32), ForeignKey("surveys.id"), nullable=False, index=True),
    Column("idx", Integer, nullable=False),
    Column("product", String(32), nullable=False),  # launch_kit | pledge
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("status", String(24), nullable=False, index=True),
    Column("capture_id", String(64)),
    Column("payer_id", String(64)),
    Column("environment", String(8), nullable=False),  # sandbox | live
    _created(),
    _updated(),
)

kits = Table(
    "kits", metadata,
    Column("token", String(64), primary_key=True),
    Column("order_id", String(64), ForeignKey("orders.id"), nullable=False, unique=True),
    Column("survey_id", String(32), ForeignKey("surveys.id"), nullable=False, index=True),
    Column("idx", Integer, nullable=False),
    Column("status", String(16), nullable=False, index=True),  # building | ready | failed | revoked
    Column("payload", JSON),
    _created(),
    _updated(),
)

campaigns = Table(
    "campaigns", metadata,
    Column("id", String(32), primary_key=True),
    Column("survey_id", String(32), ForeignKey("surveys.id"), nullable=False, index=True),
    Column("idx", Integer, nullable=False),
    Column("owner_token_hash", String(64), nullable=False),
    Column("title", String(200), nullable=False),
    Column("offer", JSON, nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("goal_count", Integer, nullable=False),
    Column("deadline", UTCDateTime, nullable=False),
    Column("status", String(16), nullable=False, index=True),  # draft | open | funded | collected | cancelled | expired
    _created(),
    _updated(),
)

pledges = Table(
    "pledges", metadata,
    Column("id", String(32), primary_key=True),
    Column("campaign_id", String(32), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("order_id", String(64), nullable=False, unique=True),
    Column("authorization_id", String(64)),
    Column("amount_cents", Integer, nullable=False),
    Column("status", String(16), nullable=False, index=True),  # created | authorized | captured | voided | expired | failed
    Column("payer_id", String(64)),
    _created(),
    Column("authorized_at", UTCDateTime),
    Column("expires_at", UTCDateTime),
    Column("captured_at", UTCDateTime),
    _updated(),
)

paypal_events = Table(
    "paypal_events", metadata,
    Column("id", String(64), primary_key=True),  # PayPal's event id, so a redelivered webhook is handled once
    Column("event_type", String(64), nullable=False),
    Column("resource_id", String(64)),
    Column("received_at", UTCDateTime, nullable=False, default=utcnow),
    Column("payload", JSON, nullable=False),
)
