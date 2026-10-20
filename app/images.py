"""Optional interior images.

- cloudflare: Workers AI FLUX.1 [schnell], which has a free daily allowance (CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN).
- openai: any OpenAI-compatible images endpoint (IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL).
"""
from __future__ import annotations

import httpx

FLUX_MODEL = "@cf/black-forest-labs/flux-1-schnell"


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
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._model = model
        self._http = http_client or httpx.AsyncClient(timeout=60)
        if self.provider == "cloudflare":
            self.enabled = bool(cf_account_id and cf_api_token)
        elif self.provider == "openai":
            self.enabled = bool(api_key and model)
        else:
            self.enabled = False

    async def aclose(self) -> None:
        await self._http.aclose()

    async def generate(self, prompt: str) -> str | None:
        """Returns a data URL (or https URL) for the image, or None when disabled or failing."""
        if not self.enabled or not prompt:
            return None
        if self.provider == "cloudflare":
            return await self._cloudflare(prompt)
        return await self._openai(prompt)

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

    async def _openai(self, prompt: str) -> str | None:
        response = await self._http.post(
            f"{self._base_url}/images/generations",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "prompt": prompt[:4000], "size": "1024x1024", "n": 1},
        )
        response.raise_for_status()
        item = (response.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            return f"data:image/png;base64,{item['b64_json']}"
        return item.get("url")
