"""OpenRouter adapter — optional cloud access, including eligible free models.

OpenRouter authenticates with a Bearer key; ``HTTP-Referer``/``X-Title`` are
recommended headers (they attribute request traffic to this app on the
dashboard). The key lives only in settings/.env and is never logged.
"""

from __future__ import annotations

import httpx

from app.core.llm.openai_compatible import OpenAICompatibleProvider

APP_SITE_URL = "http://localhost:5173"
APP_TITLE = "KnowSphere AI"


class OpenRouterProvider(OpenAICompatibleProvider):
    """Chat completions against the OpenRouter cloud API."""

    provider_name = "openrouter"

    def __init__(
        self,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str = "",
        model: str = "meta-llama/llama-3.3-70b-instruct:free",
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            provider_name=self.provider_name,
            base_url=base_url,
            model=model,
            api_key=api_key,
            extra_headers={
                "HTTP-Referer": APP_SITE_URL,
                "X-Title": APP_TITLE,
            },
            timeout=timeout,
            transport=transport,  # test seam only
        )
