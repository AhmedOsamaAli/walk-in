"""Runtime settings, read from environment variables (and a local .env file in development)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


@dataclass(frozen=True)
class Settings:
    qloo_api_key: str = field(default_factory=lambda: _env("QLOO_API_KEY"))
    qloo_base_url: str = field(default_factory=lambda: _env("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/"))
    # Any OpenAI-compatible chat endpoint. Recommended free option: Gemini's OpenAI-compatible endpoint.
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str | None = field(default_factory=lambda: _env("LLM_BASE_URL") or None)
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gemini-3.6-flash"))
    # Tried in order when the main model is rate limited, overloaded or failing (free tiers have per-model quotas).
    llm_fallback_models: tuple[str, ...] = field(
        default_factory=lambda: tuple(m.strip() for m in _env("LLM_FALLBACK_MODELS").split(",") if m.strip())
    )
    llm_timeout: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT") or 45.0)
    llm_temperature: float | None = field(default_factory=lambda: _env_float("LLM_TEMPERATURE"))
    llm_reasoning_effort: str | None = field(default_factory=lambda: _env("LLM_REASONING_EFFORT") or None)
    # Agent answers are reused when a site's evidence is unchanged, which saves the free AI quota. "0" turns it off.
    agent_cache: bool = field(default_factory=lambda: _env("AGENT_CACHE", "1") != "0")
    # Renders, tried in order (comma-separated): "cloudflare" (Workers AI FLUX, free daily allowance), "horde"
    # (AI Horde volunteer GPUs, free, no key), "gemini" (Google image models, same key as the agent; needs billing)
    # or "openai" (OpenAI-compatible images API). Example: "cloudflare,horde".
    image_provider: str = field(default_factory=lambda: _env("IMAGE_PROVIDER"))
    # Most renders the server makes per day (UTC), to cap spending on a public demo; cached renders are free.
    image_daily_limit: int = field(default_factory=lambda: int(_env_float("IMAGE_DAILY_LIMIT") or 60))
    cloudflare_image_model: str = field(
        default_factory=lambda: _env("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
    )
    # Optional: a registered AI Horde key (aihorde.net/register) earns priority; without one, renders queue anonymously.
    ai_horde_api_key: str = field(default_factory=lambda: _env("AI_HORDE_API_KEY"))
    ai_horde_model: str = field(default_factory=lambda: _env("AI_HORDE_MODEL", "Flux.1-Schnell fp8 (Compact)"))
    cloudflare_account_id: str = field(default_factory=lambda: _env("CLOUDFLARE_ACCOUNT_ID"))
    cloudflare_api_token: str = field(default_factory=lambda: _env("CLOUDFLARE_API_TOKEN"))
    image_api_key: str = field(default_factory=lambda: _env("IMAGE_API_KEY"))
    image_base_url: str | None = field(default_factory=lambda: _env("IMAGE_BASE_URL") or None)
    image_model: str = field(default_factory=lambda: _env("IMAGE_MODEL"))
    cache_dir: Path = field(default_factory=lambda: Path(_env("CACHE_DIR") or ROOT / ".cache" / "qloo"))
    walk_cache_dir: Path = field(default_factory=lambda: Path(_env("WALK_CACHE_DIR") or ROOT / ".cache" / "walk"))
    agent_cache_dir: Path = field(default_factory=lambda: Path(_env("AGENT_CACHE_DIR") or ROOT / ".cache" / "agent"))


settings = Settings()
