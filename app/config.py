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
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gemini-3.8-flash"))
    llm_temperature: float | None = field(default_factory=lambda: _env_float("LLM_TEMPERATURE"))
    llm_reasoning_effort: str | None = field(default_factory=lambda: _env("LLM_REASONING_EFFORT") or None)
    # Interior images: "cloudflare" (Workers AI FLUX, free daily allowance) or "openai" (OpenAI-compatible images API).
    image_provider: str = field(default_factory=lambda: _env("IMAGE_PROVIDER"))
    cloudflare_account_id: str = field(default_factory=lambda: _env("CLOUDFLARE_ACCOUNT_ID"))
    cloudflare_api_token: str = field(default_factory=lambda: _env("CLOUDFLARE_API_TOKEN"))
    image_api_key: str = field(default_factory=lambda: _env("IMAGE_API_KEY"))
    image_base_url: str | None = field(default_factory=lambda: _env("IMAGE_BASE_URL") or None)
    image_model: str = field(default_factory=lambda: _env("IMAGE_MODEL"))
    cache_dir: Path = field(default_factory=lambda: Path(_env("CACHE_DIR") or ROOT / ".cache" / "qloo"))
    walk_cache_dir: Path = field(default_factory=lambda: Path(_env("WALK_CACHE_DIR") or ROOT / ".cache" / "walk"))


settings = Settings()
