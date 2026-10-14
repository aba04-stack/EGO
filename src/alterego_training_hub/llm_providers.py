"""Multi-provider LLM layer: request building and response parsing.

Speaks three wire formats behind one OpenAI-style message list:

* ``openai``   — OpenAI / Codex, OpenRouter, Ollama, DeepSeek, Groq, Mistral
  and any OpenAI-compatible endpoint (``/chat/completions``, Bearer auth);
* ``anthropic`` — Claude Messages API (``/v1/messages``, ``x-api-key``);
* ``gemini``   — Google Gemini generateContent (function calling included).

Pure functions only — no network, no Tk — so the adapters are unit-testable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


class ProviderError(RuntimeError):
    """Provider configuration or response problem safe to display."""


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    api_style: str  # "openai" | "anthropic" | "gemini"
    base_url: str
    model_hint: str = ""
    allow_http_localhost: bool = False
    supports_models_list: bool = True
    supports_reasoning: bool = False
    notes: str = field(default="")


PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        "openai", "OpenAI (GPT)", "openai", "https://api.openai.com/v1",
        model_hint="gpt-5", supports_reasoning=True,
        notes="api.openai.com — GPT-семейство"),
    "codex": ProviderInfo(
        "codex", "OpenAI Codex (код)", "openai", "https://api.openai.com/v1",
        model_hint="gpt-5-codex", supports_reasoning=True,
        notes="Кодовые модели OpenAI (Codex)"),
    "anthropic": ProviderInfo(
        "anthropic", "Anthropic (Claude)", "anthropic",
        "https://api.anthropic.com", model_hint="claude-sonnet-4-5",
        notes="Messages API"),
    "gemini": ProviderInfo(
        "gemini", "Google (Gemini)", "gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        model_hint="gemini-2.5-pro", notes="generateContent API"),
    "openrouter": ProviderInfo(
        "openrouter", "OpenRouter (много моделей)", "openai",
        "https://openrouter.ai/api/v1", model_hint="",
        notes="Единый доступ к сотням моделей"),
    "ollama": ProviderInfo(
        "ollama", "Ollama (локально)", "openai", "http://localhost:11434/v1",
        model_hint="qwen3:8b", allow_http_localhost=True,
        notes="Локальные модели без облака"),
    "deepseek": ProviderInfo(
        "deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1",
        model_hint="deepseek-chat"),
    "groq": ProviderInfo(
        "groq", "Groq (быстрые)", "openai", "https://api.groq.com/openai/v1",
        model_hint="llama-3.3-70b-versatile"),
    "mistral": ProviderInfo(
        "mistral", "Mistral", "openai", "https://api.mistral.ai/v1",
        model_hint="mistral-large-latest"),
    "custom": ProviderInfo(
        "custom", "Свой OpenAI-совместимый сервер", "openai", "",
        notes="Укажите базовый URL сами"),
}

ANTHROPIC_VERSION = "2023-06-01"


def provider_info(provider_id: str) -> ProviderInfo:
    info = PROVIDERS.get(str(provider_id or "").strip().lower())
    return info if info is not None else PROVIDERS["custom"]


def provider_labels() -> list[str]:
    return [info.label for info in PROVIDERS.values()]


def provider_id_by_label(label: str) -> str:
    for info in PROVIDERS.values():
        if info.label == label:
            return info.id
    return "custom"


# ------------------------------------------------------------------ URLs
def validate_base_url(base_url: str, *, allow_http_localhost: bool = False) -> str:
    value = str(base_url or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise ProviderError("Базовый URL провайдера некорректен.") from None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderError(
            "URL не должен содержать учётные данные, параметры или фрагмент.")
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host:
        return value
    if parsed.scheme == "http" and allow_http_localhost and host in {
        "localhost", "127.0.0.1", "::1",
    }:
        return value
    raise ProviderError(
        "Базовый URL должен использовать HTTPS (для локального Ollama "
        "допустим http://localhost).")


def chat_endpoint(base_url: str, api_style: str, model: str = "") -> str:
    value = str(base_url or "").strip().rstrip("/")
    if api_style == "anthropic":
        if not value.endswith("/v1/messages"):
            if value.endswith("/v1"):
                value += "/messages"
            else:
                value += "/v1/messages"
        return value
    if api_style == "gemini":
        return value + f"/models/{model}:generateContent"
    if not value.endswith("/chat/completions"):
        value += "/chat/completions"
    return value


def models_endpoint(base_url: str, api_style: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    if api_style == "anthropic":
        if value.endswith("/v1/messages"):
            value = value[: -len("/messages")]
        elif value.endswith("/v1"):
            value += ""
        else:
            value += "/v1"
        return value + "/models"
    value = value.removesuffix("/chat/completions")
    return value + "/models"


# ------------------------------------------------------- schema conversion
def openai_tools_to_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        out.append({
            "name": str(function.get("name") or ""),
            "description": str(function.get("description") or ""),
            "input_schema": function.get("parameters")
                           or {"type": "object", "properties": {}},
        })
    return out


def openai_tools_to_gemini(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        declarations.append({
            "name": str(function.get("name") or ""),
            "description": str(function.get("description") or ""),
            "parameters": function.get("parameters")
                          or {"type": "object", "properties": {}},
        })
    return [{"functionDeclarations": declarations}] if declarations else []


# ------------------------------------------------------ openai wire format
def build_openai_payload(*, model: str, messages: list[dict[str, Any]],
                         tools: list[dict[str, Any]] | None,
                         max_tokens: int, temperature: float,
                         reasoning_effort: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    return payload


def parse_openai_response(raw: bytes, fallback_model: str) -> dict[str, Any]:
    data = _loads(raw, "OpenAI-совместимый")
    message = data["choices"][0]["message"]
    text = message.get("content") or ""
    if isinstance(text, list):
        text = "".join(
            part.get("text", "") for part in text
            if isinstance(part, dict) and part.get("type") == "text")
    if not isinstance(text, str):
        raise ProviderError("API вернул некорректный ответ.")
    tool_calls: list[Any] = []
    for raw_call in message.get("tool_calls") or []:
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function") or {}
        arguments = _load_args(function.get("arguments"))
        tool_calls.append((str(raw_call.get("id") or f"call-{len(tool_calls) + 1}"),
                           str(function.get("name") or ""), arguments))
    if not text.strip() and not tool_calls:
        raise ProviderError("API вернул пустой ответ.")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return {"text": text.strip(), "tool_calls": tool_calls,
            "model": str(data.get("model") or fallback_model), "usage": usage}


# --------------------------------------------------- anthropic wire format
def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts = [str(m.get("content") or "") for m in messages
                    if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(part for part in system_parts if part), rest


def build_anthropic_payload(*, model: str, messages: list[dict[str, Any]],
                            tools: list[dict[str, Any]] | None,
                            max_tokens: int, temperature: float,
                            reasoning_effort: str = "") -> dict[str, Any]:
    system, rest = _split_system(messages)
    converted: list[dict[str, Any]] = []
    for message in rest:
        role = message.get("role")
        if role == "user":
            converted.append({"role": "user",
                              "content": str(message.get("content") or "")})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text",
                               "text": str(message["content"])})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                blocks.append({
                    "type": "tool_use",
                    "id": str(call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "input": _load_args(function.get("arguments")),
                })
            converted.append({"role": "assistant",
                              "content": blocks or ""})
        elif role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": str(message.get("tool_call_id") or ""),
                    "content": str(message.get("content") or ""),
                }],
            })
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": converted,
    }
    if system:
        payload["system"] = system
    anthropic_tools = openai_tools_to_anthropic(tools or [])
    if anthropic_tools:
        payload["tools"] = anthropic_tools
    return payload


def parse_anthropic_response(raw: bytes, fallback_model: str) -> dict[str, Any]:
    data = _loads(raw, "Anthropic")
    text_parts: list[str] = []
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []
    content = data.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                arguments = block.get("input")
                if not isinstance(arguments, dict):
                    arguments = {}
                tool_calls.append((str(block.get("id") or
                                       f"call-{len(tool_calls) + 1}"),
                                   str(block.get("name") or ""), arguments))
    text = "".join(text_parts).strip()
    if not text and not tool_calls:
        raise ProviderError("Anthropic API вернул пустой ответ.")
    _usage_raw = data.get("usage")
    raw_usage: dict[str, Any] = _usage_raw if isinstance(_usage_raw, dict) else {}
    usage = {
        "prompt_tokens": raw_usage.get("input_tokens"),
        "completion_tokens": raw_usage.get("output_tokens"),
    }
    return {"text": text, "tool_calls": tool_calls,
            "model": str(data.get("model") or fallback_model), "usage": usage}


# ------------------------------------------------------ gemini wire format
def _gemini_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            continue
        if role == "user":
            contents.append({"role": "user",
                             "parts": [{"text": str(message.get("content") or "")}]})
        elif role == "assistant":
            parts: list[dict[str, Any]] = []
            if message.get("content"):
                parts.append({"text": str(message["content"])})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                parts.append({"functionCall": {
                    "name": str(function.get("name") or ""),
                    "args": _load_args(function.get("arguments")),
                }})
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        elif role == "tool":
            contents.append({"role": "user", "parts": [{
                "functionResponse": {
                    "name": str(message.get("name") or ""),
                    "response": {"result": str(message.get("content") or "")},
                }}]})
    return contents


def build_gemini_payload(*, model: str, messages: list[dict[str, Any]],
                         tools: list[dict[str, Any]] | None,
                         max_tokens: int, temperature: float,
                         reasoning_effort: str = "") -> dict[str, Any]:
    system, _ = _split_system(messages)
    payload: dict[str, Any] = {
        "contents": _gemini_contents(messages),
        "generationConfig": {"maxOutputTokens": max_tokens,
                             "temperature": temperature},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    declarations = openai_tools_to_gemini(tools or [])
    if declarations:
        payload["tools"] = declarations
    return payload


def parse_gemini_response(raw: bytes, fallback_model: str) -> dict[str, Any]:
    data = _loads(raw, "Gemini")
    candidates = data.get("candidates") or []
    if not candidates:
        raise ProviderError("Gemini API вернул пустой ответ.")
    content = candidates[0].get("content") or {}
    text_parts: list[str] = []
    tool_calls: list[tuple[str, str, dict[str, Any]]] = []
    for part in content.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if part.get("text"):
            text_parts.append(str(part["text"]))
        call = part.get("functionCall")
        if isinstance(call, dict):
            arguments = call.get("args")
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append((f"call-{len(tool_calls) + 1}",
                               str(call.get("name") or ""), arguments))
    text = "".join(text_parts).strip()
    if not text and not tool_calls:
        raise ProviderError("Gemini API вернул пустой ответ.")
    _usage_raw = data.get("usageMetadata")
    raw_usage: dict[str, Any] = _usage_raw if isinstance(_usage_raw, dict) else {}
    usage = {
        "prompt_tokens": raw_usage.get("promptTokenCount"),
        "completion_tokens": raw_usage.get("candidatesTokenCount"),
    }
    return {"text": text, "tool_calls": tool_calls,
            "model": str(data.get("modelVersion") or fallback_model),
            "usage": usage}


# ------------------------------------------------------------- dispatchers
def build_chat_payload(api_style: str, **kwargs: Any) -> dict[str, Any]:
    if api_style == "anthropic":
        return build_anthropic_payload(**kwargs)
    if api_style == "gemini":
        return build_gemini_payload(**kwargs)
    return build_openai_payload(**kwargs)


def parse_chat_response(api_style: str, raw: bytes,
                        fallback_model: str) -> dict[str, Any]:
    if api_style == "anthropic":
        return parse_anthropic_response(raw, fallback_model)
    if api_style == "gemini":
        return parse_gemini_response(raw, fallback_model)
    return parse_openai_response(raw, fallback_model)


def chat_headers(api_style: str, api_key: str) -> dict[str, str]:
    if api_style == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
                "Content-Type": "application/json",
                "Accept": "application/json"}
    if api_style == "gemini":
        return {"x-goog-api-key": api_key, "Content-Type": "application/json",
                "Accept": "application/json"}
    return {"Authorization": "Bearer " + api_key,
            "Content-Type": "application/json", "Accept": "application/json"}


def models_headers(api_style: str, api_key: str) -> dict[str, str]:
    headers = chat_headers(api_style, api_key)
    headers.pop("Content-Type", None)
    return headers


def parse_model_list(api_style: str, raw: bytes) -> list[str]:
    data = _loads(raw, "список моделей")
    items = data.get("data") if isinstance(data.get("data"), list) else None
    if items is None and isinstance(data.get("models"), list):
        items = data["models"]
    if not isinstance(items, list):
        raise ProviderError("Провайдер вернул некорректный список моделей.")
    models = set()
    for item in items:
        if isinstance(item, dict):
            value = item.get("id") or item.get("name") or ""
            if value:
                models.add(str(value).removeprefix("models/"))
    return sorted(models)


# ----------------------------------------------------------------- helpers
def _loads(raw: bytes, what: str) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ProviderError(f"API ({what}) вернул некорректный JSON.") from None
    if not isinstance(data, dict):
        raise ProviderError(f"API ({what}) вернул некорректный ответ.")
    return data


def _load_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise ProviderError("Модель прислала некорректные аргументы инструмента.") from None
        if isinstance(parsed, dict):
            return parsed
    return {}


def redact(text: str, api_key: str) -> str:
    value = str(text)
    if api_key:
        value = value.replace(api_key, "[REDACTED]")
    return value
