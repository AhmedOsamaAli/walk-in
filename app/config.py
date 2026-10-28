"""Runtime settings, read from environment variables (and a local .env file in development)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
# The Vite dev server, which may call the API from another port in development.
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_float(name: str) -> float | None:
    value = _env(name)
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _env_list(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in _env(name, default).split(",") if item.strip())


def _env_or(name: str, default: float) -> float:
    value = _env_float(name)
    return default if value is None else value


def _env_flag(name: str) -> bool:
    return _env(name).lower() in ("1", "true", "yes", "on")


def origin_of(url: str) -> str | None:
    """'https://Example.com/path' -> 'https://example.com'; None when the URL has no scheme and host."""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


@dataclass(frozen=True)
class Settings:
    qloo_api_key: str = field(default_factory=lambda: _env("QLOO_API_KEY"))
    qloo_base_url: str = field(default_factory=lambda: _env("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/"))
    # Any OpenAI-compatible chat endpoint. Recommended free option: Gemini's OpenAI-compatible endpoint.
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str | None = field(default_factory=lambda: _env("LLM_BASE_URL") or None)
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gemini-3.6-flash"))
    # Tried in order when the main model is rate limited, overloaded or failing (free tiers have per-model quotas).
    llm_fallback_models: tuple[str, ...] = field(default_factory=lambda: _env_list("LLM_FALLBACK_MODELS"))
    llm_timeout: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT") or 45.0)
    llm_temperature: float | None = field(default_factory=lambda: _env_float("LLM_TEMPERATURE"))
    llm_reasoning_effort: str | None = field(default_factory=lambda: _env("LLM_REASONING_EFFORT") or None)
    # Longest wait, in seconds, for a resting model to come back before the agent hands over to the evidence rules.
    llm_max_wait: float = field(default_factory=lambda: _env_or("LLM_MAX_WAIT", 40.0))
    # A second free provider whose models follow the main chain (console.groq.com/keys). Its free tier allows 1,000
    # requests a day and 8,000 tokens a minute per model, so long agent conversations are cut to fit.
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    groq_base_url: str = field(default_factory=lambda: _env("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    groq_models: tuple[str, ...] = field(
        default_factory=lambda: _env_list("GROQ_MODELS", "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b")
    )
    groq_reasoning_effort: str | None = field(default_factory=lambda: _env("GROQ_REASONING_EFFORT", "low") or None)
    groq_token_limit: int = field(default_factory=lambda: int(_env_or("GROQ_TOKEN_LIMIT", 8000)))
    # Agent answers are reused when a site's evidence is unchanged, which saves the free AI quota. "0" turns it off.
    agent_cache: bool = field(default_factory=lambda: _env("AGENT_CACHE", "1") != "0")
    # Most launch kits the server builds per day (UTC); each one asks the model for its ad copy.
    kit_daily_limit: int = field(default_factory=lambda: int(_env_or("KIT_DAILY_LIMIT", 60)))
    cache_dir: Path = field(default_factory=lambda: Path(_env("CACHE_DIR") or ROOT / ".cache" / "qloo"))
    walk_cache_dir: Path = field(default_factory=lambda: Path(_env("WALK_CACHE_DIR") or ROOT / ".cache" / "walk"))
    agent_cache_dir: Path = field(default_factory=lambda: Path(_env("AGENT_CACHE_DIR") or ROOT / ".cache" / "agent"))
    # Where users, surveys, design sheets and launch kits live: a local SQLite file by default, or a Postgres URL (Neon's
    # free tier, for example) on a host whose disk does not survive a restart.
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL") or f"sqlite:///{(ROOT / '.data' / 'walkin.db').as_posix()}"
    )
    # Surveys older than this are deleted on startup, with their kits, unless a signed-in user keeps them in My places.
    survey_retention_days: int = field(default_factory=lambda: int(_env_or("SURVEY_RETENTION_DAYS", 60)))
    # Finished surveys anyone can open before running their own (comma-separated survey ids): GET /api/examples. They
    # are never deleted, and opening one replays what was saved, so it spends no Qloo or AI quota.
    examples: tuple[str, ...] = field(default_factory=lambda: _env_list("EXAMPLES"))
    # The app's public address (https://...). When it is https, cookies are Secure and the development login is off.
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL").rstrip("/"))
    # Sign in with Google (console.cloud.google.com, Google Auth Platform > Clients): the web client's ID. Without it
    # nobody can sign in, so nothing is kept in My places; surveys work as before.
    google_client_id: str = field(default_factory=lambda: _env("GOOGLE_CLIENT_ID"))
    # Days a sign-in lasts; using the app renews it, at most once a day.
    session_days: int = field(default_factory=lambda: int(_env_or("SESSION_DAYS", 30)))
    # Development only: POST /api/auth/dev signs in with any email. Ignored when PUBLIC_URL is https.
    auth_dev_login: bool = field(default_factory=lambda: _env_flag("AUTH_DEV_LOGIN"))
    # Other origins whose pages may POST to the API (comma-separated), besides PUBLIC_URL's and the server's own.
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: _env_list("ALLOWED_ORIGINS"))
    # Shared with the Cloudflare front door (frontend/functions): with it, X-Client-IP is the visitor's own address.
    proxy_secret: str = field(default_factory=lambda: _env("PROXY_SECRET"))
    # Walk-in Founders: PayPal (developer.paypal.com, Apps & Credentials), the sandbox until PAYPAL_ENV=live. Without
    # the keys nobody can pledge, and the pages say why.
    paypal_client_id: str = field(default_factory=lambda: _env("PAYPAL_CLIENT_ID"))
    paypal_client_secret: str = field(default_factory=lambda: _env("PAYPAL_CLIENT_SECRET"))
    paypal_env: str = field(default_factory=lambda: _env("PAYPAL_ENV", "sandbox").lower())
    # The webhook registered for this server's address (docs/founders/setup_paypal_webhook.py writes it); without it
    # POST /api/paypal/webhook does not exist, and settlement keeps pledges and payouts in step on its own.
    paypal_webhook_id: str = field(default_factory=lambda: _env("PAYPAL_WEBHOOK_ID"))
    # The secret a scheduled job sends to POST /api/cron/settle (X-Cron-Secret); without it that endpoint does not exist.
    cron_secret: str = field(default_factory=lambda: _env("CRON_SECRET"))
    # Seconds between the in-app settlement passes (0 turns the loop off; the cron endpoint still settles).
    settle_every: float = field(default_factory=lambda: _env_or("SETTLE_EVERY_S", 180.0))
    # For the judging weeks, once Qloo's hackathon key is switched off: GET /api/run answers 503, and the web app shows
    # the surveyed storefronts instead.
    surveys_paused: bool = field(default_factory=lambda: _env_flag("SURVEYS_PAUSED"))

    @property
    def hosted(self) -> bool:
        """Whether this is the hosted site (PUBLIC_URL is https) rather than development."""
        return self.public_url.startswith("https://")

    @property
    def dev_login(self) -> bool:
        return self.auth_dev_login and not self.hosted

    @property
    def trusted_origins(self) -> frozenset[str]:
        """Origins whose pages may call the API's unsafe methods, besides the server's own."""
        origins = {origin_of(url) for url in (self.public_url, *self.allowed_origins)}
        if not self.hosted:
            origins.update(DEV_ORIGINS)
        return frozenset(origin for origin in origins if origin)

    @property
    def paypal_enabled(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def paypal_environment(self) -> str:
        """'live' with PAYPAL_ENV=live, else 'sandbox': anything else never reaches real money."""
        return "live" if self.paypal_env == "live" else "sandbox"

    @property
    def paypal_api_base(self) -> str:
        return "https://api-m.paypal.com" if self.paypal_environment == "live" else "https://api-m.sandbox.paypal.com"


settings = Settings()
