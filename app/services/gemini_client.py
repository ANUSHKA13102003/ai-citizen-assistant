"""Gemini wrapper (google-genai SDK) with cached model fallback on 404/429/503/504 and friendly errors."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterator

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

FRIENDLY_ERROR = (
    "Showing answers from our verified scheme data while live help is busy."
)
FRIENDLY_NO_KEY = (
    "Showing answers from our verified scheme data. Document upload, details and the "
    "Scheme Finder all work normally."
)

_RESOLVED_LOCK = threading.Lock()
_RESOLVED_MODELS: dict[str, str] = {}
_UNAVAILABLE_MODELS: set[str] = set()
_CACHED_TEXT_MODELS: list[str] | None = None
_KEY_HEALTH: str = "unknown"
_LAST_RETEST_TS: float = 0.0
_RETEST_INTERVAL_SEC = 600.0


def get_key_health(api_key: str) -> str:
    if not (api_key or "").strip():
        return "missing"
    return _KEY_HEALTH if _KEY_HEALTH != "unknown" else "ok"


def _is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        t in msg
        for t in ("401", "403", "api_key_invalid", "api key not valid", "permission_denied", "unauthenticated")
    )

_EXCLUDE_TOKENS = (
    "tts",
    "image",
    "audio",
    "live",
    "embedding",
    "transcribe",
    "omni",
    "robotics",
    "computer-use",
    "thinking",
    "exp",
)

_FAST_PREFERRED = (
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
)


class GeminiUnavailableError(RuntimeError):
    """Raised when generation fails. `user_message` is always safe to show to users."""

    def __init__(self, internal: str, user_message: str = FRIENDLY_ERROR) -> None:
        super().__init__(internal)
        self.user_message = user_message


def _is_not_found(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "404" in msg or "not_found" in msg or "not found" in msg or "no longer available" in msg


def _is_model_overloaded_or_quota(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        t in msg
        for t in (
            "429",
            "503",
            "504",
            "resource_exhausted",
            "quota",
            "unavailable",
            "high demand",
            "overloaded",
            "gateway timeout",
        )
    )


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        t in msg
        for t in (
            "429",
            "500",
            "503",
            "504",
            "timeout",
            "unavailable",
            "resource_exhausted",
            "rate",
            "deadline",
            "overloaded",
            "high demand",
        )
    )


def _version_key(name: str) -> tuple:
    is_lite = "lite" in name
    fast_rank = (
        len(_FAST_PREFERRED) - _FAST_PREFERRED.index(name) if name in _FAST_PREFERRED else 0
    )
    nums = re.findall(r"(\d+(?:\.\d+)?)", name)
    ver = float(nums[0]) if nums else 0.0
    is_preview = "preview" in name
    is_latest_alias = name.endswith("latest")
    return (not is_lite, fast_rank, ver, not is_preview, not is_latest_alias)


def rank_flash_models(model_names: list[str], exclude: set[str] | None = None) -> list[str]:
    """Return available general-purpose flash text models ordered best-first."""
    excluded = exclude or set()
    candidates = []
    for raw in model_names:
        name = raw.removeprefix("models/")
        if name in excluded:
            continue
        if "flash" not in name or not name.startswith("gemini"):
            continue
        if any(tok in name for tok in _EXCLUDE_TOKENS):
            continue
        candidates.append(name)
    return sorted(set(candidates), key=_version_key, reverse=True)


def pick_best_flash(model_names: list[str], exclude: set[str] | None = None) -> str | None:
    """Choose the best general-purpose flash text model from a list of model ids."""
    ranked = rank_flash_models(model_names, exclude=exclude)
    return ranked[0] if ranked else None


class GeminiClient:
    def __init__(self, api_key: str, model: str, max_retries: int = 3, base_backoff: float = 1.5):
        self.api_key = (api_key or "").strip()
        self.requested_model = model
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._client: genai.Client | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def model(self) -> str:
        global _LAST_RETEST_TS
        now = time.time()
        with _RESOLVED_LOCK:
            if (
                self.requested_model in _RESOLVED_MODELS
                and _RESOLVED_MODELS[self.requested_model] != self.requested_model
                and now - _LAST_RETEST_TS > _RETEST_INTERVAL_SEC
            ):
                _LAST_RETEST_TS = now
                _UNAVAILABLE_MODELS.discard(self.requested_model)
                _RESOLVED_MODELS.pop(self.requested_model, None)
            resolved = _RESOLVED_MODELS.get(self.requested_model, self.requested_model)
            if resolved in _UNAVAILABLE_MODELS and _CACHED_TEXT_MODELS:
                alt = pick_best_flash(_CACHED_TEXT_MODELS, exclude=_UNAVAILABLE_MODELS)
                if alt:
                    _RESOLVED_MODELS[self.requested_model] = alt
                    return alt
            return resolved

    def _get_client(self) -> genai.Client:
        if not self.is_configured:
            raise GeminiUnavailableError("Gemini key missing", FRIENDLY_NO_KEY)
        if self._client is None:
            try:
                http_opts = types.HttpOptions(
                    timeout=25_000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                )
                self._client = genai.Client(api_key=self.api_key, http_options=http_opts)
            except Exception:
                self._client = genai.Client(api_key=self.api_key)
        return self._client

    def list_text_models(self) -> list[str]:
        global _CACHED_TEXT_MODELS
        with _RESOLVED_LOCK:
            if _CACHED_TEXT_MODELS is not None:
                return list(_CACHED_TEXT_MODELS)
        client = self._get_client()
        names = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                names.append(m.name.removeprefix("models/"))
        with _RESOLVED_LOCK:
            _CACHED_TEXT_MODELS = names
        return list(names)

    def _fallback_model(self, failed_model: str) -> str | None:
        with _RESOLVED_LOCK:
            _UNAVAILABLE_MODELS.add(failed_model)
        try:
            models = self.list_text_models()
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Could not list Gemini models: %s", type(exc).__name__)
            return None
        with _RESOLVED_LOCK:
            best = pick_best_flash(models, exclude=_UNAVAILABLE_MODELS)
            if best:
                _RESOLVED_MODELS[self.requested_model] = best
                logger.warning(
                    "Gemini model '%s' unavailable; falling back to '%s'",
                    failed_model,
                    best,
                )
                return best
        return None

    @staticmethod
    def _contents(user_prompt: str, history: list[dict[str, str]] | None) -> list[types.Content]:
        contents: list[types.Content] = []
        for msg in history or []:
            role = "user" if msg.get("role") == "user" else "model"
            text = (msg.get("content") or "").strip()
            if text:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)]))
        return contents

    @staticmethod
    def _make_config(
        system_prompt: str,
        temperature: float,
        response_mime_type: str | None = None,
        thinking_budget: int | None = 0,
        model_name: str = "",
    ) -> types.GenerateContentConfig:
        cfg: dict = {"system_instruction": system_prompt, "temperature": temperature}
        if response_mime_type:
            cfg["response_mime_type"] = response_mime_type
        if (
            thinking_budget is not None
            and "lite" not in (model_name or "").lower()
            and hasattr(types, "ThinkingConfig")
        ):
            try:
                cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
            except Exception:
                pass
        return types.GenerateContentConfig(**cfg)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.1,
        response_mime_type: str | None = None,
    ) -> str:
        client = self._get_client()
        contents = self._contents(user_prompt, history)
        disable_thinking = False

        last_err: Exception | None = None
        model_retries = 0
        fallback_hops = 0
        while fallback_hops < 10:
            current_model = self.model
            config = self._make_config(
                system_prompt,
                temperature,
                response_mime_type,
                thinking_budget=None if disable_thinking else 0,
                model_name=current_model,
            )
            try:
                resp = client.models.generate_content(
                    model=current_model, contents=contents, config=config
                )
                global _KEY_HEALTH
                _KEY_HEALTH = "ok"
                with _RESOLVED_LOCK:
                    _RESOLVED_MODELS[self.requested_model] = current_model
                logger.info("Gemini generation succeeded using model '%s'", current_model)
                return (resp.text or "").strip()
            except Exception as exc:
                last_err = exc
                if _is_auth_error(exc):
                    _KEY_HEALTH = "invalid"
                    raise GeminiUnavailableError("Gemini auth failed", FRIENDLY_NO_KEY) from exc
                if (
                    not disable_thinking
                    and getattr(config, "thinking_config", None) is not None
                    and ("thinking" in str(exc).lower() or "400" in str(exc) or "invalid_argument" in str(exc).lower())
                ):
                    disable_thinking = True
                    continue
                if _is_not_found(exc):
                    fallback_hops += 1
                    model_retries = 0
                    if self._fallback_model(current_model):
                        continue
                    break
                if (_is_model_overloaded_or_quota(exc) or _is_transient(exc)) and model_retries < 1:
                    time.sleep(self.base_backoff * (2**model_retries))
                    model_retries += 1
                    continue
                if _is_model_overloaded_or_quota(exc):
                    fallback_hops += 1
                    model_retries = 0
                    if self._fallback_model(current_model):
                        continue
                break
        logger.error("Gemini generation failed (%s)", type(last_err).__name__ if last_err else "?")
        raise GeminiUnavailableError(str(last_err)) from last_err

    def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.2,
        on_retry=None,
    ) -> Iterator[str]:
        client = self._get_client()
        contents = self._contents(user_prompt, history)
        model_retries = 0
        fallback_hops = 0
        disable_thinking = False
        last_err: Exception | None = None
        while fallback_hops < 10:
            emitted = False
            current_model = self.model
            config = self._make_config(
                system_prompt,
                temperature,
                thinking_budget=None if disable_thinking else 0,
                model_name=current_model,
            )
            try:
                for chunk in client.models.generate_content_stream(
                    model=current_model, contents=contents, config=config
                ):
                    text = getattr(chunk, "text", None)
                    if text:
                        emitted = True
                        yield text
                global _KEY_HEALTH
                _KEY_HEALTH = "ok"
                with _RESOLVED_LOCK:
                    _RESOLVED_MODELS[self.requested_model] = current_model
                logger.info("Gemini stream succeeded using model '%s'", current_model)
                return
            except Exception as exc:
                last_err = exc
                if emitted:
                    raise GeminiUnavailableError(str(exc)) from exc
                if _is_auth_error(exc):
                    _KEY_HEALTH = "invalid"
                    raise GeminiUnavailableError("Gemini auth failed", FRIENDLY_NO_KEY) from exc
                if (
                    not disable_thinking
                    and getattr(config, "thinking_config", None) is not None
                    and ("thinking" in str(exc).lower() or "400" in str(exc) or "invalid_argument" in str(exc).lower())
                ):
                    disable_thinking = True
                    continue
                if _is_not_found(exc):
                    fallback_hops += 1
                    model_retries = 0
                    if on_retry:
                        on_retry("Busy right now, trying again...")
                    if self._fallback_model(current_model):
                        continue
                    break
                if (_is_model_overloaded_or_quota(exc) or _is_transient(exc)) and model_retries < 1:
                    if on_retry:
                        on_retry("Busy right now, trying again...")
                    time.sleep(self.base_backoff * (2**model_retries))
                    model_retries += 1
                    continue
                if _is_model_overloaded_or_quota(exc):
                    fallback_hops += 1
                    model_retries = 0
                    if on_retry:
                        on_retry("Busy right now, trying again...")
                    if self._fallback_model(current_model):
                        continue
                break
        logger.error("Gemini streaming failed (%s)", type(last_err).__name__ if last_err else "?")
        raise GeminiUnavailableError(str(last_err)) from last_err
