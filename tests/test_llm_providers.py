"""Tests for the multi-provider LLM request/response adapters (no network)."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.llm_providers import (
    ProviderError,
    build_anthropic_payload,
    build_chat_payload,
    build_gemini_payload,
    build_openai_payload,
    chat_endpoint,
    chat_headers,
    models_endpoint,
    parse_anthropic_response,
    parse_chat_response,
    parse_gemini_response,
    parse_model_list,
    parse_openai_response,
    provider_info,
    validate_base_url,
)

MESSAGES = [
    {"role": "system", "content": "Be careful."},
    {"role": "user", "content": "прочитай файл"},
    {"role": "assistant", "content": "",
     "tool_calls": [{"id": "call-1", "type": "function",
                     "function": {"name": "read_file",
                                  "arguments": "{\"path\": \"a.py\"}"}}]},
    {"role": "tool", "tool_call_id": "call-1", "name": "read_file",
     "content": "print(1)"},
]
TOOLS = [{"type": "function", "function": {
    "name": "read_file", "description": "read", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}}}}}]


def test_provider_registry_covers_popular_ai():
    for pid in ("openai", "codex", "anthropic", "gemini", "openrouter",
                "ollama", "deepseek", "groq", "mistral", "custom"):
        assert provider_info(pid).id == pid
    assert provider_info("anthropic").api_style == "anthropic"
    assert provider_info("gemini").api_style == "gemini"
    assert provider_info("ollama").allow_http_localhost
    assert provider_info("nope").id == "custom"  # unknown falls back


def test_validate_base_url_rules():
    assert validate_base_url("https://api.openai.com/v1")
    assert validate_base_url("http://localhost:11434/v1",
                             allow_http_localhost=True)
    for bad in ("http://api.openai.com/v1", "https://u:p@host/v1",
                "https://host/v1?key=x", "not-a-url", ""):
        with pytest.raises(ProviderError):
            validate_base_url(bad)
    with pytest.raises(ProviderError):
        validate_base_url("http://localhost:11434/v1")  # without the flag


def test_endpoints_per_style():
    assert chat_endpoint("https://x/v1", "openai").endswith("/chat/completions")
    assert chat_endpoint("https://x", "anthropic").endswith("/v1/messages")
    assert chat_endpoint("https://x/v1beta", "gemini", "m1") == \
        "https://x/v1beta/models/m1:generateContent"
    assert models_endpoint("https://x/v1", "anthropic").endswith("/v1/models")
    assert models_endpoint("https://x/v1beta", "gemini").endswith("/v1beta/models")


def test_openai_payload_and_parse_roundtrip():
    payload = build_openai_payload(model="m", messages=MESSAGES, tools=TOOLS,
                                   max_tokens=100, temperature=0.2)
    assert payload["tool_choice"] == "auto"
    raw = json.dumps({
        "model": "m", "usage": {"prompt_tokens": 1},
        "choices": [{"message": {"content": "", "tool_calls": [{
            "id": "call-9", "function": {"name": "run_command",
                                          "arguments": "{\"command\": \"ls\"}"}}]}}],
    }).encode()
    parsed = parse_openai_response(raw, "m")
    assert parsed["tool_calls"][0][1] == "run_command"
    assert parsed["tool_calls"][0][2] == {"command": "ls"}


def test_anthropic_payload_conversion():
    payload = build_anthropic_payload(model="claude-x", messages=MESSAGES,
                                      tools=TOOLS, max_tokens=100,
                                      temperature=0.2)
    assert payload["system"] == "Be careful."
    assert payload["tools"][0]["input_schema"]["type"] == "object"
    roles = [message["role"] for message in payload["messages"]]
    assert roles == ["user", "assistant", "user"]
    assistant_blocks = payload["messages"][1]["content"]
    assert assistant_blocks[0]["type"] == "tool_use"
    assert assistant_blocks[0]["input"] == {"path": "a.py"}
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"


def test_anthropic_parse_tool_use_and_usage():
    raw = json.dumps({
        "model": "claude-x",
        "usage": {"input_tokens": 5, "output_tokens": 7},
        "content": [
            {"type": "text", "text": "готово"},
            {"type": "tool_use", "id": "tu-1", "name": "write_file",
             "input": {"path": "a", "content": "x"}},
        ],
    }).encode()
    parsed = parse_anthropic_response(raw, "fb")
    assert parsed["text"] == "готово"
    assert parsed["tool_calls"] == [("tu-1", "write_file",
                                     {"path": "a", "content": "x"})]
    assert parsed["usage"]["prompt_tokens"] == 5


def test_gemini_payload_conversion_and_parse():
    payload = build_gemini_payload(model="gemini-x", messages=MESSAGES,
                                   tools=TOOLS, max_tokens=100,
                                   temperature=0.2)
    assert payload["systemInstruction"]["parts"][0]["text"] == "Be careful."
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "read_file"
    roles = [item["role"] for item in payload["contents"]]
    assert roles == ["user", "model", "user"]
    model_parts = payload["contents"][1]["parts"]
    assert model_parts[0]["functionCall"]["name"] == "read_file"

    raw = json.dumps({
        "modelVersion": "gemini-2.5",
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4},
        "candidates": [{"content": {"parts": [
            {"text": "ок"},
            {"functionCall": {"name": "run_command", "args": {"command": "ls"}}},
        ]}}],
    }).encode()
    parsed = parse_gemini_response(raw, "fb")
    assert parsed["text"] == "ок"
    assert parsed["tool_calls"][0][1] == "run_command"
    assert parsed["model"] == "gemini-2.5"


def test_dispatchers_and_headers():
    assert build_chat_payload("openai", model="m", messages=MESSAGES,
                              tools=None, max_tokens=1, temperature=0.0)["model"] == "m"
    assert chat_headers("anthropic", "k")["x-api-key"] == "k"
    assert chat_headers("anthropic", "k")["anthropic-version"]
    assert chat_headers("gemini", "k")["x-goog-api-key"] == "k"
    assert chat_headers("openai", "k")["Authorization"] == "Bearer k"
    with pytest.raises(ProviderError):
        parse_chat_response("openai", b"not json", "m")
    models = parse_model_list("gemini", json.dumps({
        "models": [{"name": "models/gemini-2.5-pro"}]}).encode())
    assert models == ["gemini-2.5-pro"]


def test_invalid_tool_arguments_rejected():
    raw = json.dumps({
        "choices": [{"message": {"content": "", "tool_calls": [{
            "id": "c1", "function": {"name": "x", "arguments": "{bad"}}]}}],
    }).encode()
    with pytest.raises(ProviderError):
        parse_openai_response(raw, "m")
