"""The database's tables, as SQLAlchemy Core. The migrations in migrations/ create them; keep both in step.

Users sign in with Google; a session row holds only the SHA-256 of its cookie. The app writes surveys and their design
sheets, for anyone, and records the signed-in user and the browser (device) that ran each. A finished survey's state is
kept as zlib-compressed JSON (app.db.surveys): it runs to megabytes, and compresses about sevenfold. Launch kits, one
per survey concept, live and go with their survey.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Dialect,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
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
    # The finished run (app.survey.snapshot) as zlib-compressed JSON, so it can still be designed after a restart.
    Column("state", LargeBinary),
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

kits = Table(
    "kits", metadata,
    Column("token", String(64), primary_key=True),  # random, in the kit's link: anyone with the link can open the kit
    Column("survey_id", String(32), ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
    Column("idx", Integer, nullable=False),  # the concept's position in the survey's concepts
    Column("status", String(16), nullable=False),  # building | ready | failed
    Column("name", String(200)),  # the business's name, for the kit's page and My places
    Column("payload", JSON),  # app.survey.kit.build_kit's kit, dossier included, once ready
    Column("error", String(500)),  # why the last build failed, in plain words
    _created(),
    _updated(),
    UniqueConstraint("survey_id", "idx"),  # one kit per concept
)
