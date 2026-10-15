"""Local inference servers (stage 43): Ollama / vLLM / LM Studio.

Probe a running server, start/stop Ollama from the app, and generate
through the OpenAI-compatible endpoint (vLLM, LM Studio and Ollama
all expose one).  Network and process operations accept injectable
callables so tests stay offline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

OLLAMA_URL = "http://localhost:11434"
VLLM_URL = "http://localhost:8000"


@dataclass
class ServerStatus:
    kind: str
    url: str
    up: bool = False
    models: list[str] = field(default_factory=list)
    detail: str = ""

    def render(self) -> str:
        if not self.up:
            return f"{self.kind}: не отвечает ({self.detail or self.url})"
        models = ", ".join(self.models[:6]) or "моделей нет"
        return f"{self.kind}: работает · {models}"


def _get_json(url: str, timeout: float = 3.0) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": "AlterEgo-LLM-Studio"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def probe_ollama(url: str = OLLAMA_URL,
                 fetcher: Callable | None = None) -> ServerStatus:
    fetch = fetcher or _get_json
    try:
        data = fetch(url.rstrip("/") + "/api/tags")
    except Exception as exc:
        return ServerStatus("Ollama", url, detail=type(exc).__name__)
    models = [m.get("name", "") for m in (data or {}).get("models", [])]
    return ServerStatus("Ollama", url, up=True,
                        models=[m for m in models if m])


def probe_openai_compat(kind: str, url: str,
                        fetcher: Callable | None = None) -> ServerStatus:
    """vLLM / LM Studio / any OpenAI-compatible ``GET /v1/models``."""
    fetch = fetcher or _get_json
    try:
        data = fetch(url.rstrip("/") + "/v1/models")
    except Exception as exc:
        return ServerStatus(kind, url, detail=type(exc).__name__)
    models = [m.get("id", "") for m in (data or {}).get("data", [])]
    return ServerStatus(kind, url, up=True,
                        models=[m for m in models if m])


def probe_all(fetcher: Callable | None = None) -> list[ServerStatus]:
    return [probe_ollama(fetcher=fetcher),
            probe_openai_compat("vLLM", VLLM_URL, fetcher=fetcher)]


class LocalServerManager:
    """Start/stop a local Ollama server process (never raises)."""

    def __init__(self, runner: Callable | None = None):
        self._runner = runner  # tests: fake Popen factory
        self._process: Any = None
        self.kind = ""

    def available(self, kind: str = "ollama") -> bool:
        return shutil.which(kind) is not None

    def start(self, kind: str = "ollama") -> ServerStatus:
        if self._process is not None and self._process.poll() is None:
            return ServerStatus(kind, OLLAMA_URL, up=True,
                                detail="уже запущен из приложения")
        binary = shutil.which(kind)
        if not binary:
            return ServerStatus(kind, OLLAMA_URL,
                                detail=f"{kind} не найден в PATH")
        try:
            if self._runner is not None:
                self._process = self._runner([binary, "serve"])
            else:
                self._process = subprocess.Popen(
                    [binary, "serve"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return ServerStatus(kind, OLLAMA_URL, detail=str(exc))
        self.kind = kind
        return ServerStatus(kind, OLLAMA_URL, up=True,
                            detail="запущен, дайте ему секунду на старт")

    def stop(self) -> bool:
        if self._process is None:
            return False
        try:
            self._process.terminate()
        except Exception:
            return False
        self._process = None
        return True

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None
