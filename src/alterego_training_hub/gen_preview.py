"""Generation preview: see *what the model generates* while it trains.

The training command can print samples in a documented line format (any of)::

    {"sample": {"step": 100, "prompt": "…", "text": "…", "checkpoint": "best"}}
    ### sample @100 [best]
    prompt: …
    text: …

This module parses them from the training log tail, formats them for the UI
and compares two samples (e.g. from different checkpoints) on the same prompt.

Pure logic — no tkinter, no network.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

_BLOCK_RE = re.compile(
    r"^###\s*sample\s*@(?P<step>\d+)(?:\s*\[(?P<ckpt>[^\]]+)\])?\s*$")
_PROMPT_RE = re.compile(r"^prompt:\s?(?P<body>.*)$")
_TEXT_RE = re.compile(r"^text:\s?(?P<body>.*)$")


@dataclass(frozen=True)
class GenerationSample:
    """One generated text sample produced during training."""

    step: int
    prompt: str
    text: str
    checkpoint: str = ""

    def line(self) -> str:
        ckpt = f" [{self.checkpoint}]" if self.checkpoint else ""
        preview = " ".join(self.text.split())[:80]
        return f"шаг {self.step}{ckpt} · «{self.prompt[:40]}» → {preview}"


def perplexity_from_loss(loss: float) -> float:
    """exp(loss); inf for invalid/negative loss.

    Canonical implementation lives in :func:`evaluation.perplexity`
    (single source of truth, этап 36); negative/invalid losses stay ``inf``
    here because a generation sample with negative loss is meaningless.
    """
    try:
        value = float(loss)
    except (TypeError, ValueError):
        return float("inf")
    if value < 0 or math.isnan(value) or value in (float("inf"), float("-inf")):
        return float("inf")
    from .evaluation import perplexity

    result = perplexity(value)
    return result if result == result else float("inf")


def _sample_from_json(data: dict) -> GenerationSample | None:
    payload = data.get("sample") if isinstance(data.get("sample"), dict) else data
    if not isinstance(payload, dict):
        return None
    if "prompt" not in payload and "text" not in payload:
        return None
    try:
        step = int(payload.get("step", 0) or 0)
    except (TypeError, ValueError):
        step = 0
    return GenerationSample(
        step=step,
        prompt=str(payload.get("prompt", "")),
        text=str(payload.get("text", "")),
        checkpoint=str(payload.get("checkpoint", "") or ""))


def parse_samples(log_text: str) -> list[GenerationSample]:
    """Extract samples from a training log tail (JSONL lines or ### blocks)."""
    samples: list[GenerationSample] = []
    lines = (log_text or "").splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if stripped.startswith("{") and ("sample" in stripped or "prompt" in stripped):
            try:
                data = json.loads(stripped)
            except ValueError:
                data = None
            if isinstance(data, dict):
                sample = _sample_from_json(data)
                if sample is not None and (sample.prompt or sample.text):
                    samples.append(sample)
                index += 1
                continue
        match = _BLOCK_RE.match(stripped)
        if match:
            step = int(match.group("step"))
            ckpt = match.group("ckpt") or ""
            prompt = ""
            text_lines: list[str] = []
            index += 1
            mode = ""
            while index < len(lines):
                line = lines[index]
                if _BLOCK_RE.match(line.strip()) or line.strip().startswith("{"):
                    break
                prompt_match = _PROMPT_RE.match(line)
                text_match = _TEXT_RE.match(line)
                if prompt_match:
                    mode = "prompt"
                    prompt = prompt_match.group("body")
                elif text_match:
                    mode = "text"
                    text_lines = [text_match.group("body")]
                elif mode == "text":
                    text_lines.append(line)
                elif mode == "prompt":
                    prompt += "\n" + line
                index += 1
            samples.append(GenerationSample(
                step=step, prompt=prompt.strip(),
                text="\n".join(text_lines).strip(), checkpoint=ckpt))
            continue
        index += 1
    return samples


def format_sample(sample: GenerationSample, *, max_text: int = 600) -> str:
    """Card-style rendering of one sample for the UI/дashboards."""
    rows = [f"Шаг: {sample.step}"
            + (f" · чекпоинт: {sample.checkpoint}" if sample.checkpoint else ""),
            f"Промпт: {sample.prompt or '—'}",
            "Генерация:"]
    body = (sample.text or "—").strip()
    if len(body) > max_text:
        body = body[:max_text] + " …"
    rows.append(body)
    return "\n".join(rows)


def format_samples(samples: Iterable[GenerationSample], *, limit: int = 5) -> str:
    """List rendering of the latest samples (empty string when none)."""
    items = list(samples)
    if not items:
        return ""
    rows = [format_sample(sample) for sample in items[-limit:]]
    return "\n\n".join(rows)


def compare_samples(a: GenerationSample, b: GenerationSample) -> str:
    """Compare two generations on the same prompt (e.g. two checkpoints)."""
    rows: list[str] = []
    if a.prompt.strip() and b.prompt.strip() and a.prompt.strip() != b.prompt.strip():
        rows.append("⚠ Промпты различаются — сравнение условное.")
    rows.append(f"Шаг {a.step} [{a.checkpoint or '—'}] vs "
                f"шаг {b.step} [{b.checkpoint or '—'}]")
    rows.append(f"Длина: {len(a.text)} vs {len(b.text)} символов")
    shorter = min(len(a.text), len(b.text))
    common = 0
    while common < shorter and a.text[common] == b.text[common]:
        common += 1
    share = (common / shorter * 100) if shorter else 100.0
    rows.append(f"Общее начало: {share:.0f}%")
    rows.append("")
    rows.append(f"--- A (шаг {a.step}) ---")
    rows.append(a.text.strip()[:600] or "—")
    rows.append(f"--- B (шаг {b.step}) ---")
    rows.append(b.text.strip()[:600] or "—")
    return "\n".join(rows)
