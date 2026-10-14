"""Explicit API mentor calls for OpenAI-compatible, Anthropic and Gemini providers."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import llm_providers
from .llm_providers import ProviderError, provider_info


class MentorError(RuntimeError):
    """A provider configuration or request error safe for display."""


@dataclass(frozen=True)
class ToolCall:
    """One function call requested by the mentor model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MentorReply:
    text: str
    model: str
    usage: dict[str, Any]
    request_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


def _as_mentor_error(exc: ProviderError) -> MentorError:
    return MentorError(str(exc))


def chat_endpoint(base_url: str, api_style: str = "openai", model: str = "") -> str:
    try:
        llm_providers.validate_base_url(base_url)
        return llm_providers.chat_endpoint(base_url, api_style, model)
    except ProviderError as exc:
        raise _as_mentor_error(exc) from None


def models_endpoint(base_url: str, api_style: str = "openai") -> str:
    try:
        llm_providers.validate_base_url(base_url)
        return llm_providers.models_endpoint(base_url, api_style)
    except ProviderError as exc:
        raise _as_mentor_error(exc) from None


DEFAULT_SYSTEM_PROMPT = (
    "You are a careful AI research mentor. Separate verified facts from "
    "hypotheses, state uncertainty, and recommend measurable tests."
)


class ApiMentor:
    """Unified client for all supported LLM providers.

    ``api_style`` selects the wire format (``openai``, ``anthropic``,
    ``gemini``); ``provider`` is the registry id used for defaults
    (e.g. ``ollama`` allows ``http://localhost``).
    """

    def __init__(self, base_url: str, model: str, api_key: str,
                 timeout_seconds: float = 60, *, api_style: str = "openai",
                 provider: str = "", reasoning_effort: str = ""):
        info = provider_info(provider) if provider else None
        self.provider = (provider or "custom").strip().lower()
        if api_style in {"openai", "anthropic", "gemini"}:
            self.api_style = api_style
        elif info is not None:
            self.api_style = info.api_style
        else:
            self.api_style = "openai"
        self.allow_http_localhost = bool(info.allow_http_localhost) if info else False
        self.reasoning_effort = str(reasoning_effort or "").strip().lower()
        if self.reasoning_effort not in {"", "off", "low", "medium", "high"}:
            self.reasoning_effort = ""
        self.base_url = str(base_url).strip()
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = float(timeout_seconds)
        if not self.model or not self.api_key:
            raise MentorError("Choose a model and store its API key before testing the mentor.")
        if not 1 <= self.timeout_seconds <= 300:
            raise MentorError("Timeout must be between 1 and 300 seconds.")
        try:
            llm_providers.validate_base_url(
                self.base_url, allow_http_localhost=self.allow_http_localhost)
        except ProviderError as exc:
            raise _as_mentor_error(exc) from None
        self.endpoint = chat_endpoint(self.base_url, self.api_style, self.model)

    # -- shared transport ------------------------------------------------
    def _post_chat(self, payload: dict[str, Any]) -> tuple[bytes, str | None]:
        headers = llm_providers.chat_headers(self.api_style, self.api_key)
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise MentorError("Mentor response exceeded 4 MiB.")
                request_id = response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(2500).decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            detail = llm_providers.redact(detail, self.api_key)[:900]
            raise MentorError(f"Mentor API returned HTTP {exc.code}. {detail}".strip()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MentorError(f"Could not connect to mentor API ({type(exc).__name__}).") from None
        return raw, request_id

    def _parse_reply(self, raw: bytes, request_id: str | None) -> MentorReply:
        try:
            parsed = llm_providers.parse_chat_response(self.api_style, raw,
                                                       self.model)
        except ProviderError as exc:
            raise _as_mentor_error(exc) from None
        tool_calls = tuple(
            ToolCall(id=call_id, name=name, arguments=arguments)
            for call_id, name, arguments in parsed["tool_calls"]
        )
        return MentorReply(
            text=parsed["text"],
            model=parsed["model"],
            usage=parsed["usage"],
            request_id=request_id,
            tool_calls=tool_calls,
        )

    # -- public API ------------------------------------------------------
    def respond(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 700,
        temperature: float = 0.2,
    ) -> MentorReply:
        """Send a full conversation (OpenAI message list) and return the reply."""
        if not isinstance(messages, list) or not messages:
            raise MentorError("Conversation history must not be empty.")
        for item in messages:
            if not isinstance(item, dict) or "role" not in item:
                raise MentorError("Conversation history contains an invalid message.")
        try:
            max_tokens = int(max_tokens)
            temperature = float(temperature)
        except (TypeError, ValueError):
            raise MentorError("Max response tokens and temperature must be numbers.") from None
        if not 1 <= max_tokens <= 8000:
            raise MentorError("Max response tokens must be between 1 and 8000.")
        if not 0.0 <= temperature <= 2.0:
            raise MentorError("Temperature must be between 0 and 2.")
        effort = self.reasoning_effort if self.reasoning_effort != "off" else ""
        payload = llm_providers.build_chat_payload(
            self.api_style,
            model=self.model,
            messages=messages,
            tools=tools or None,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=effort,
        )
        raw, request_id = self._post_chat(payload)
        return self._parse_reply(raw, request_id)

    def ask(
        self,
        prompt: str,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = 700,
        temperature: float = 0.2,
    ) -> MentorReply:
        if not isinstance(prompt, str) or not prompt.strip():
            raise MentorError("Prompt must not be empty.")
        return self.respond(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def list_models(self) -> list[str]:
        """Return model IDs advertised by the provider's models endpoint."""
        url = models_endpoint(self.base_url, self.api_style)
        headers = llm_providers.models_headers(self.api_style, self.api_key)
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout_seconds, 30.0)) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise MentorError("Model list response exceeded 2 MiB.")
        except urllib.error.HTTPError as exc:
            raise MentorError(f"Model list request returned HTTP {exc.code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MentorError(f"Could not fetch the model list ({type(exc).__name__}).") from None
        try:
            return llm_providers.parse_model_list(self.api_style, raw)
        except ProviderError as exc:
            raise _as_mentor_error(exc) from None


def build_mentor(*, provider: str, base_url: str, model: str, api_key: str,
                 timeout_seconds: float = 60,
                 reasoning_effort: str = "") -> ApiMentor:
    """Construct an :class:`ApiMentor` using provider defaults from the registry."""
    info = provider_info(provider)
    url = (base_url or "").strip() or info.base_url
    return ApiMentor(
        url, model, api_key,
        timeout_seconds=timeout_seconds,
        api_style=info.api_style,
        provider=info.id,
        reasoning_effort=reasoning_effort,
    )
