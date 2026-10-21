"""Optional AI renders of a concept: the full interior and the shopfront seen from the street.

- gemini: Google's image models (gemini-3.1-flash-image, gemini-3-pro-image) with a Gemini API key. They render
  readable sign lettering. Image models are not in Gemini's free tier, so the key's project needs billing.
- cloudflare: Workers AI FLUX.1 [schnell], which has a free daily allowance (CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN).
- openai: any OpenAI-compatible images endpoint, e.g. gpt-image-1 (IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL).
"""
from __future__ import annotations

import httpx

FLUX_MODEL = "@cf/black-forest-labs/flux-1-schnell"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"


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
    ) -> None:
        self.provider = provider.strip().lower()
        self._cf_account_id = cf_account_id
        self._cf_api_token = cf_api_token
        self._api_key = api_key
        self._http_client = http_client
        if self.provider == "gemini":
            self._base_url = (base_url or GEMINI_BASE_URL).rstrip("/")
            self._model = model or GEMINI_IMAGE_MODEL
            self.enabled = bool(api_key)
        else:
            self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
            self._model = model
            if self.provider == "cloudflare":
                self.enabled = bool(cf_account_id and cf_api_token)
            elif self.provider == "openai":
                self.enabled = bool(api_key and model)
            else:
                self.enabled = False

    @property
    def model(self) -> str | None:
        """The model that renders, for credits in the UI."""
        if not self.enabled:
            return None
        return FLUX_MODEL.rsplit("/", 1)[-1] if self.provider == "cloudflare" else self._model

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
            return await self._cloudflare(prompt)
        return await self._openai(prompt, aspect)

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

    async def _cloudflare(self, prompt: str) -> str | None:
        url = f"https://api.cloudflare.com/client/v4/accounts/{self._cf_account_id}/ai/run/{FLUX_MODEL}"
        response = await self._http.post(
            url,
            headers={"Authorization": f"Bearer {self._cf_api_token}"},
            json={"prompt": prompt[:2048], "steps": 6},
        )
        response.raise_for_status()
        image = (response.json().get("result") or {}).get("image")
        return f"data:image/jpeg;base64,{image}" if image else None

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
    return "The image model could not render this right now."


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
