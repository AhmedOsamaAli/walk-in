"""Optional AI renders of a concept: the full interior and the shopfront seen from the street.

Providers, tried in the order IMAGE_PROVIDER lists them (e.g. "cloudflare,horde"):
- cloudflare: Workers AI, free daily allowance of 10,000 neurons (CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN).
  FLUX.2 [klein] 4B (the default) takes a size and spells signs right (~100 a day free, ~30 s each); FLUX.1 [schnell]
  is faster but square, with garbled lettering (~130 a day free).
- horde: AI Horde, a free, open-source network of volunteer GPUs (github.com/Haidra-Org/AI-Horde). No key needed;
  renders wait in a public queue, typically one to three minutes.
- gemini: Google's image models (gemini-3.1-flash-image, gemini-3-pro-image) with a Gemini API key. They render
  readable sign lettering. Image models are not in Gemini's free tier, so the key's project needs billing.
- openai: any OpenAI-compatible images endpoint, e.g. gpt-image-1 (IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time

import httpx

log = logging.getLogger("blankspace")

FLUX_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
HORDE_BASE_URL = "https://aihorde.net/api/v2"
HORDE_MODEL = "Flux.1-Schnell fp8 (Compact)"
HORDE_ANONYMOUS_KEY = "0000000000"
# AI Horde asks every client to identify itself as name:version:contact.
HORDE_CLIENT_AGENT = "blank-space:1.0:github.com/AhmedOsamaAli"


class ImageGen:
    def __init__(
        self,
        provider: str = "",
        cf_account_id: str = "",
        cf_api_token: str = "",
        api_key: str = "",
        base_url: str | None = None,
        model: str = "",
        http_client: httpx.AsyncClient | None = None,
        wait_s: float = 240.0,
        poll_s: float = 4.0,
    ) -> None:
        self.provider = provider.strip().lower()
        self._cf_account_id = cf_account_id
        self._cf_api_token = cf_api_token
        self._api_key = api_key
        self._http_client = http_client
        self._wait_s, self._poll_s = wait_s, poll_s
        self._jobs: dict[str, str] = {}  # AI Horde jobs still queued, by prompt and size; a retry resumes them
        if self.provider == "gemini":
            self._base_url = (base_url or GEMINI_BASE_URL).rstrip("/")
            self._model = model or GEMINI_IMAGE_MODEL
            self.enabled = bool(api_key)
        elif self.provider == "horde":
            self._base_url = (base_url or HORDE_BASE_URL).rstrip("/")
            self._model = model or HORDE_MODEL
            self._api_key = api_key or HORDE_ANONYMOUS_KEY
            self.enabled = True
        elif self.provider == "cloudflare":
            self._base_url = ""
            self._model = model or FLUX_MODEL
            self.enabled = bool(cf_account_id and cf_api_token)
        else:
            self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
            self._model = model
            self.enabled = self.provider == "openai" and bool(api_key and model)

    @property
    def model(self) -> str | None:
        """The model that renders, for credits in the UI."""
        if not self.enabled:
            return None
        if self.provider == "cloudflare":
            return self._model.rsplit("/", 1)[-1]
        if self.provider == "horde":
            return f"{self._model} on AI Horde"
        return self._model

    @property
    def _http(self) -> httpx.AsyncClient:
        # Created on first use, so a disabled generator never loads TLS certificates. Renders can take a minute.
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=120)
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()

    async def generate(self, prompt: str, aspect: str = "16:9") -> str | None:
        """A data URL (or https URL) for the image; None when disabled. Provider errors raise.

        aspect is a width:height ratio; providers that only make square images ignore it.
        """
        if not self.enabled or not prompt:
            return None
        if self.provider == "gemini":
            return await self._gemini(prompt, aspect)
        if self.provider == "cloudflare":
            return await self._cloudflare(prompt, aspect)
        if self.provider == "horde":
            return await self._horde(prompt, aspect)
        return await self._openai(prompt, aspect)

    async def render(self, prompt: str, aspect: str = "16:9") -> tuple[str | None, str | None]:
        """The image and the model that made it."""
        return await self.generate(prompt, aspect), self.model

    async def _gemini(self, prompt: str, aspect: str) -> str | None:
        url = f"{self._base_url}/models/{self._model}:generateContent"
        config: dict = {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}
        body = {"contents": [{"parts": [{"text": prompt[:4000]}]}], "generationConfig": config}
        response = await self._http.post(url, headers={"x-goog-api-key": self._api_key}, json=body)
        if response.status_code == 400 and "imageConfig" in response.text:
            # Older image models reject the aspect ratio setting; they return a square image instead.
            del config["imageConfig"]
            response = await self._http.post(url, headers={"x-goog-api-key": self._api_key}, json=body)
        response.raise_for_status()
        for candidate in response.json().get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if inline.get("data"):
                    return f"data:{inline.get('mimeType') or 'image/png'};base64,{inline['data']}"
        return None

    async def _cloudflare(self, prompt: str, aspect: str) -> str | None:
        url = f"https://api.cloudflare.com/client/v4/accounts/{self._cf_account_id}/ai/run/{self._model}"
        response = await self._http.post(
            url,
            headers={"Authorization": f"Bearer {self._cf_api_token}"},
            **cloudflare_body(self._model, prompt, aspect),
        )
        response.raise_for_status()
        image = (response.json().get("result") or {}).get("image")
        return data_url(image) if image else None

    async def _horde(self, prompt: str, aspect: str) -> str | None:
        width, height = sized(aspect, long_side=1024, multiple=64)
        key = f"{self._model}|{width}x{height}|{prompt}"
        agent = {"Client-Agent": HORDE_CLIENT_AGENT}
        for _ in range(2):
            job = self._jobs.get(key) or await self._horde_submit(prompt, width, height)
            self._jobs[key] = job
            deadline = time.monotonic() + self._wait_s
            try:
                while True:
                    await asyncio.sleep(self._poll_s)
                    check = await self._http.get(f"{self._base_url}/generate/check/{job}", headers=agent)
                    if check.status_code == 404:
                        break  # the Horde dropped the job (it expires after a while): submit it again
                    check.raise_for_status()
                    state = check.json()
                    if state.get("faulted"):
                        self._jobs.pop(key, None)
                        raise RuntimeError("AI Horde could not render this image.")
                    if state.get("done"):
                        self._jobs.pop(key, None)
                        return await self._horde_result(job)
                    if time.monotonic() > deadline:
                        # The job keeps its place in the queue; the next request for this shot resumes it.
                        raise TimeoutError(f"AI Horde queue still busy after {self._wait_s:.0f} s.")
            except asyncio.CancelledError:
                # The server is shutting down: leave the volunteers' queue so nobody renders an unseen image.
                self._jobs.pop(key, None)
                try:
                    await self._http.delete(f"{self._base_url}/generate/status/{job}", headers=agent)
                except Exception:
                    log.debug("Could not cancel AI Horde job %s", job, exc_info=True)
                raise
            self._jobs.pop(key, None)
        raise RuntimeError("AI Horde kept dropping this job.")

    async def _horde_submit(self, prompt: str, width: int, height: int) -> str:
        headers = {"apikey": self._api_key, "Client-Agent": HORDE_CLIENT_AGENT}
        body = {
            "prompt": prompt[:1500],
            "params": {"width": width, "height": height, "steps": 4, "cfg_scale": 1, "sampler_name": "k_euler", "n": 1},
            "models": [self._model],
            "nsfw": False,
            "censor_nsfw": True,
            "r2": True,
        }
        for attempt in range(3):
            response = await self._http.post(f"{self._base_url}/generate/async", headers=headers, json=body)
            if response.status_code != 429:
                break
            await asyncio.sleep(1.5 * (attempt + 1))  # the Horde accepts two submissions a second per client
        response.raise_for_status()
        return response.json()["id"]

    async def _horde_result(self, job: str) -> str | None:
        status = await self._http.get(f"{self._base_url}/generate/status/{job}", headers={"Client-Agent": HORDE_CLIENT_AGENT})
        status.raise_for_status()
        generations = status.json().get("generations") or []
        if not generations or generations[0].get("censored"):
            return None
        image = generations[0].get("img") or ""
        if not image.startswith("https://"):
            return data_url(image) if image else None
        download = await self._http.get(image)
        download.raise_for_status()
        mime = download.headers.get("content-type", "image/webp").split(";")[0].strip()
        return f"data:{mime};base64,{base64.b64encode(download.content).decode()}"

    async def _openai(self, prompt: str, aspect: str = "1:1") -> str | None:
        response = await self._http.post(
            f"{self._base_url}/images/generations",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "prompt": prompt[:4000], "size": openai_size(self._model, aspect), "n": 1},
        )
        response.raise_for_status()
        item = (response.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            return f"data:image/png;base64,{item['b64_json']}"
        return item.get("url")


class ImageChain:
    """Image providers tried in order: one that fails, hangs or is out of free quota hands over to the next."""

    def __init__(self, providers: list[ImageGen]) -> None:
        self.providers = providers

    @property
    def enabled(self) -> bool:
        return any(p.enabled for p in self.providers)

    @property
    def provider(self) -> str:
        return ",".join(p.provider for p in self.providers if p.enabled)

    @property
    def model(self) -> str | None:
        return next((p.model for p in self.providers if p.enabled), None)

    async def render(self, prompt: str, aspect: str = "16:9") -> tuple[str | None, str | None]:
        error: Exception | None = None
        for provider in self.providers:
            if not provider.enabled:
                continue
            try:
                image = await provider.generate(prompt, aspect)
            except Exception as exc:
                log.warning("Image provider %s failed; trying the next one", provider.provider, exc_info=True)
                error = exc
                continue
            if image:
                return image, provider.model
        if error:
            raise error
        return None, None

    async def generate(self, prompt: str, aspect: str = "16:9") -> str | None:
        return (await self.render(prompt, aspect))[0]

    async def aclose(self) -> None:
        for provider in self.providers:
            await provider.aclose()


Images = ImageGen | ImageChain


def explain_failure(exc: Exception) -> str:
    """A message a visitor can act on, for a failed render."""
    if isinstance(exc, httpx.HTTPStatusError):
        status, body = exc.response.status_code, exc.response.text
        if status == 429 and "limit: 0" in body:
            return "This image model is not in the free tier: turn on billing for the key to render."
        if status == 429:
            return "The image model's quota is used up for now. Try again later."
        if status in (401, 403):
            return "The image model rejected the key."
    if isinstance(exc, TimeoutError):
        return "Still waiting in the free volunteer queue."
    return "The image model could not render this right now."


def cloudflare_body(model: str, prompt: str, aspect: str) -> dict:
    """FLUX.1 takes JSON and makes square images; FLUX.2 takes a multipart form with the size."""
    if "flux-2" in model:
        width, height = sized(aspect, long_side=1280, multiple=16)
        fields = {"prompt": prompt[:2048], "width": str(width), "height": str(height)}
        return {"files": {name: (None, value) for name, value in fields.items()}}
    return {"json": {"prompt": prompt[:2048], "steps": 6}}


def sized(aspect: str, long_side: int, multiple: int) -> tuple[int, int]:
    """Pixel size for a width:height ratio, with sides rounded to a multiple the model accepts."""
    try:
        width, height = (float(side) for side in aspect.split(":"))
    except ValueError:
        width = height = 1.0
    if width <= 0 or height <= 0:
        width = height = 1.0
    scale = long_side / max(width, height)

    def snap(value: float) -> int:
        return max(multiple, round(value / multiple) * multiple)

    return snap(width * scale), snap(height * scale)


def data_url(image: str) -> str:
    """A data URL for a base64 image, with the type read from its first bytes."""
    if image.startswith("data:"):
        return image
    mime = "image/png" if image.startswith("iVBOR") else "image/webp" if image.startswith("UklGR") else "image/jpeg"
    return f"data:{mime};base64,{image}"


def openai_size(model: str, aspect: str) -> str:
    """gpt-image models make landscape images; other OpenAI-compatible models get the universal square size."""
    if model.lower().startswith("gpt-image"):
        width, _, height = aspect.partition(":")
        try:
            if float(width) > float(height):
                return "1536x1024"
            if float(width) < float(height):
                return "1024x1536"
        except ValueError:
            pass
    return "1024x1024"
