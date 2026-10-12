"""LLM playground: probe single models or compare A/B answers with latency."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import app_data_dir
from .mentor import ApiMentor, MentorError


@dataclass(frozen=True)
class PlaygroundResult:
    model: str
    prompt: str
    output: str
    latency_ms: int
    temperature: float
    max_tokens: int
    created_at: float = field(default_factory=time.time)
    error: str = ""

    def ok(self) -> bool:
        return not self.error


class PlaygroundClient:
    """One-shot generation against an OpenAI-compatible chat endpoint."""

    def __init__(self, base_url: str, model: str, api_key: str,
                 timeout_seconds: float = 90.0):
        self.model = model.strip() or "?"
        self._mentor = ApiMentor(base_url, model, api_key,
                                 timeout_seconds=timeout_seconds)

    def generate(self, prompt: str, *, system: str = "",
                 temperature: float = 0.7, max_tokens: int = 512) -> PlaygroundResult:
        if not isinstance(prompt, str) or not prompt.strip():
            raise MentorError("Промпт не должен быть пустым.")
        messages = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        started = time.monotonic()
        try:
            reply = self._mentor.respond(
                messages, max_tokens=max_tokens, temperature=temperature)
            latency = int((time.monotonic() - started) * 1000)
            return PlaygroundResult(
                model=reply.model or self.model,
                prompt=prompt,
                output=reply.text,
                latency_ms=latency,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
            )
        except MentorError as exc:
            latency = int((time.monotonic() - started) * 1000)
            return PlaygroundResult(
                model=self.model, prompt=prompt, output="", latency_ms=latency,
                temperature=float(temperature), max_tokens=int(max_tokens),
                error=str(exc),
            )


class PlaygroundStore:
    """Saved probe history (JSONL) — no API keys, prompts and outputs only."""

    MAX_ITEMS = 200

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else (app_data_dir() / "playground.jsonl")

    def save(self, result: PlaygroundResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        self._trim()

    def _trim(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) > self.MAX_ITEMS * 1.2:
            self.path.write_text("\n".join(lines[-self.MAX_ITEMS:]) + "\n",
                                 encoding="utf-8")

    def recent(self, limit: int = 20) -> list[PlaygroundResult]:
        if not self.path.exists():
            return []
        results: list[PlaygroundResult] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in reversed(lines[-200:]):
            try:
                raw = json.loads(line)
                results.append(PlaygroundResult(**{
                    key: value for key, value in raw.items()
                    if key in PlaygroundResult.__dataclass_fields__
                }))
            except (json.JSONDecodeError, TypeError):
                continue
            if len(results) >= limit:
                break
        return results
