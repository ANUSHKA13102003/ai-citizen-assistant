"""Gemini generation wrapper using the official google-genai SDK with retry & streaming."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiUnavailableError(RuntimeError):
    """Raised when Gemini API key is missing or the service fails after retries."""


class GeminiClient:
    """Thin wrapper around google.genai.Client for grounded generation & SSE streaming."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model or "gemini-2.5-flash"
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._client: genai.Client | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> genai.Client:
        if not self.is_configured:
            raise GeminiUnavailableError(
                "GEMINI_API_KEY is not configured. Add your Gemini API key in .env or "
                "Hugging Face Space secrets to enable live AI generation."
            )
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _build_contents(
        self, user_prompt: str, history: list[dict[str, str]] | None = None
    ) -> list[types.Content]:
        contents: list[types.Content] = []
        for msg in history or []:
            role = "user" if msg.get("role") == "user" else "model"
            text = (msg.get("content") or "").strip()
            if text:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)]))
        return contents

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.1,
        response_mime_type: str | None = None,
    ) -> str:
        """Call Gemini synchronously with exponential backoff retry on transient errors."""
        client = self._get_client()
        contents = self._build_contents(user_prompt, history)
        config_kwargs: dict = {
            "system_instruction": system_prompt,
            "temperature": temperature,
        }
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        config = types.GenerateContentConfig(**config_kwargs)

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                return (response.text or "").strip()
            except Exception as exc:
                last_err = exc
                msg = str(exc).lower()
                transient = any(
                    tok in msg for tok in ["429", "503", "500", "timeout", "unavailable", "rate"]
                )
                if transient and attempt < self.max_retries - 1:
                    sleep_s = self.base_backoff * (2**attempt)
                    logger.warning(
                        "Gemini transient error (%s); retrying in %.1fs...", exc, sleep_s
                    )
                    time.sleep(sleep_s)
                    continue
                break

        raise GeminiUnavailableError(f"Gemini generation failed: {last_err}") from last_err

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.1,
    ) -> Iterator[str]:
        """Stream response tokens from Gemini for SSE chat responses."""
        client = self._get_client()
        contents = self._build_contents(user_prompt, history)
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
        )
        try:
            for chunk in client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            ):
                if getattr(chunk, "text", None):
                    yield chunk.text
        except Exception as exc:
            raise GeminiUnavailableError(f"Gemini streaming failed: {exc}") from exc
