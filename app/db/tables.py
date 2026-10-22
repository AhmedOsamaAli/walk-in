"""The database's tables, as SQLAlchemy Core. The migrations in migrations/ create them; keep both in step.

Users sign in with Google; a session row holds only the SHA-256 of its cookie. The app writes surveys and their design
sheets, for anyone, and records the signed-in user and the browser (device) that ran each. Orders, kits, campaigns,
pledges and PayPal events are for launch kits and pledges paid with PayPal: amounts are integer cents (whole units for
currencies without cents), and ids that come from PayPal are PayPal's.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Dialect,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
)
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


def _user() -> Column:
    return Column("user_id", String(32), ForeignKey("users.id"), index=True)


users = Table(
    "users", metadata,
    Column("id", String(32), primary_key=True),
    Column("subject", String(255), nullable=False, unique=True),  # "google:<sub>", or "dev:<email>" in development
    Column("email", String(320), nullable=False),
    Column("name", String(200), nullable=False),
    Column("picture", String(1024)),
    _created(),
    _updated(),
)

sessions = Table(
    "sessions", metadata,
    Column("token_hash", String(64), primary_key=True),  # SHA-256 of the walkin_session cookie, never the cookie
    Column("user_id", String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    _created(),
    Column("expires_at", UTCDateTime, nullable=False, index=True),
)

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
    _user(),  # who ran it, when signed in (or who signed in later in the same browser)
    Column("device_id", String(32), index=True),  # the browser that ran it: its walkin_device cookie
    Column("headline", String(200)),  # the top concept's name, or the top gap, for My places
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
    Column("status", String(24), nullable=False, index=True),  # created | pending | completed | failed | refunded
    Column("capture_id", String(64)),
    Column("payer_id", String(64)),
    Column("environment", String(8), nullable=False),  # sandbox | live
    _created(),
    _updated(),
    _user(),  # the buyer
)

kits = Table(
    "kits", metadata,
    Column("token", String(64), primary_key=True),
    Column("order_id", String(64), ForeignKey("orders.id"), nullable=False, unique=True),
    Column("survey_id", String(32), ForeignKey("surveys.id"), nullable=False, index=True),
    Column("idx", Integer, nullable=False),
    Column("status", String(16), nullable=False, index=True),  # building | ready | failed | refunded
    Column("payload", JSON),
    _created(),
    _updated(),
    _user(),  # the owner
    Column("name", String(200)),  # the business's name
    Column("error", String(500)),  # why the last build failed, in plain words
)

campaigns = Table(
    "campaigns", metadata,
    Column("id", String(32), primary_key=True),
    Column("survey_id", String(32), ForeignKey("surveys.id"), nullable=False, index=True),
    Column("idx", Integer, nullable=False),
    Column("owner_token_hash", String(64)),  # unused since owners sign in
    Column("title", String(200), nullable=False),
    Column("offer", JSON, nullable=False),  # the page: pitch, perks, how it works, discount, business and concept
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("goal_count", Integer, nullable=False),
    Column("deadline", UTCDateTime, nullable=False),
    Column("status", String(16), nullable=False, index=True),  # open | funded | partial | collected | expired | cancelled
    _created(),
    _updated(),
    _user(),  # the owner
    Column("kit_token", String(64), ForeignKey("kits.token"), index=True),  # the kit it started from
    Column("closed_at", UTCDateTime),  # when the owner closed or cancelled it before the deadline
    Column("funded", Boolean),  # decided once it closes: whether it met its goal; null until then
    Column("report", JSON),  # the last settlement's report, in plain words
)

pledges = Table(
    "pledges", metadata,
    Column("id", String(32), primary_key=True),
    Column("campaign_id", String(32), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("order_id", String(64), nullable=False, unique=True),
    Column("authorization_id", String(64)),
    Column("amount_cents", Integer, nullable=False),
    Column("status", String(16), nullable=False, index=True),  # created | authorized | declined | captured | voided | expired | failed
    Column("payer_id", String(64)),
    _created(),
    Column("authorized_at", UTCDateTime),
    Column("expires_at", UTCDateTime),
    Column("captured_at", UTCDateTime),
    _updated(),
    Column("reauthorization_id", String(64)),  # the renewed hold, captured instead of the original
    Column("reauthorized_at", UTCDateTime),
    Column("capture_id", String(64)),
    Column("error", String(64)),  # PayPal's code for why the last settlement could not finish it
    Column("withdraw_token_hash", String(64), unique=True),  # SHA-256 of the supporter's withdraw link token
)

paypal_events = Table(
    "paypal_events", metadata,
    Column("id", String(64), primary_key=True),  # PayPal's event id, so a redelivered webhook is handled once
    Column("event_type", String(64), nullable=False),
    Column("resource_id", String(64)),
    Column("received_at", UTCDateTime, nullable=False, default=utcnow),
    Column("payload", JSON, nullable=False),
)
