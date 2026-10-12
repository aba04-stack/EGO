"""Explicit API mentor calls for OpenAI-compatible providers."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


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


def _validate_https_url(base_url: str, what: str) -> urllib.parse.SplitResult:
    try:
        parsed = urllib.parse.urlsplit(str(base_url).strip())
    except ValueError:
        raise MentorError(f"{what} URL is invalid.") from None
    if parsed.scheme != "https" or not parsed.hostname:
        raise MentorError(f"{what} must use an absolute HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MentorError(f"{what} URL must not contain credentials, query, or fragment.")
    return parsed


def chat_endpoint(base_url: str) -> str:
    parsed = _validate_https_url(base_url, "Mentor API")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urllib.parse.urlunsplit(("https", parsed.netloc, path, "", ""))


def models_endpoint(base_url: str) -> str:
    parsed = _validate_https_url(base_url, "Mentor API")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if not path.endswith("/models"):
        path += "/models"
    return urllib.parse.urlunsplit(("https", parsed.netloc, path, "", ""))


DEFAULT_SYSTEM_PROMPT = (
    "You are a careful AI research mentor. Separate verified facts from "
    "hypotheses, state uncertainty, and recommend measurable tests."
)


class ApiMentor:
    def __init__(self, base_url: str, model: str, api_key: str, timeout_seconds: float = 60):
        self.base_url = str(base_url).strip()
        self.endpoint = chat_endpoint(base_url)
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = float(timeout_seconds)
        if not self.model or not self.api_key:
            raise MentorError("Choose a model and store its API key before testing the mentor.")
        if not 1 <= self.timeout_seconds <= 300:
            raise MentorError("Timeout must be between 1 and 300 seconds.")

    # -- shared transport ------------------------------------------------
    def _post_chat(self, payload: dict[str, Any]) -> tuple[bytes, str | None]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
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
            detail = detail.replace(self.api_key, "[REDACTED]")[:900]
            raise MentorError(f"Mentor API returned HTTP {exc.code}. {detail}".strip()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MentorError(f"Could not connect to mentor API ({type(exc).__name__}).") from None
        return raw, request_id

    def _parse_reply(self, raw: bytes, request_id: str | None) -> MentorReply:
        try:
            data = json.loads(raw.decode("utf-8"))
            message = data["choices"][0]["message"]
            text = message.get("content") or ""
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "")
                    for part in text
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            if not isinstance(text, str):
                raise ValueError("invalid content")
        except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            raise MentorError("Mentor API returned an invalid or empty response.") from None

        tool_calls: list[ToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                raise MentorError("Mentor API returned invalid tool arguments.") from None
            if not isinstance(arguments, dict):
                raise MentorError("Mentor API returned invalid tool arguments.")
            tool_calls.append(
                ToolCall(
                    id=str(raw_call.get("id") or f"call-{len(tool_calls) + 1}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )

        if not text.strip() and not tool_calls:
            raise MentorError("Mentor API returned an invalid or empty response.")

        usage = data.get("usage", {})
        return MentorReply(
            text=text.strip(),
            model=str(data.get("model") or self.model),
            usage=usage if isinstance(usage, dict) else {},
            request_id=request_id,
            tool_calls=tuple(tool_calls),
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
        try:
            max_tokens = int(max_tokens)
            temperature = float(temperature)
        except (TypeError, ValueError):
            raise MentorError("Max response tokens and temperature must be numbers.") from None
        if not 1 <= max_tokens <= 8000:
            raise MentorError("Max response tokens must be between 1 and 8000.")
        if not 0.0 <= temperature <= 2.0:
            raise MentorError("Temperature must be between 0 and 2.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
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
        """Return model IDs advertised by the provider's /models endpoint."""
        url = models_endpoint(self.base_url)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Accept": "application/json",
            },
            method="GET",
        )
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
            data = json.loads(raw.decode("utf-8"))
            items = data["data"]
            if not isinstance(items, list):
                raise TypeError("model list")
        except (UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            raise MentorError("Provider returned an invalid model list.") from None
        models = sorted({
            str(item.get("id"))
            for item in items
            if isinstance(item, dict) and item.get("id")
        })
        return models
