"""Structured mentor assessments: strengths, weaknesses, risks, reasoning.

The mentor is asked to answer with a fenced `````report`` JSON block; parsing
also understands plain section headings so a provider without strict JSON
output still fills the report card.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import app_data_dir


@dataclass
class ModelReport:
    score: float | None = None
    reasoning: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: float = field(default_factory=time.time)

    def is_empty(self) -> bool:
        return not (self.reasoning or self.strengths or self.weaknesses
                    or self.risks or self.recommendations or self.score is not None)


REPORT_PROMPT_TEMPLATE = (
    "Дай структурированную оценку модели и обучения.\n\n"
    "Строго ответь в таком формате (один блок):\n"
    "```report\n"
    "{{\"score\": <0..10>, \"reasoning\": \"<рассуждение>\", "
    "\"strengths\": [\"<что хорошо>\"], \"weaknesses\": [\"<что плохо>\"], "
    "\"risks\": [\"<риски>\"], \"recommendations\": [\"<рекомендации>\"]}}\n"
    "```\n\n"
    "Контекст:\n{context}"
)

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "reasoning": ("рассуждение", "обоснование", "анализ", "reasoning", "analysis"),
    "strengths": ("что хорошо", "сильные стороны", "плюсы", "достоинства", "strengths", "good"),
    "weaknesses": ("что плохо", "слабые стороны", "минусы", "недостатки", "weaknesses", "bad"),
    "risks": ("риски", "опасности", "угрозы", "risks"),
    "recommendations": ("рекомендации", "что улучшить", "следующие шаги", "план",
                        "recommendations", "next steps"),
}
_FENCE_RE = re.compile(r"```(?:report|json)\s*\n(\{.*?\})\s*\n```", re.DOTALL)
_HEADER_RE = re.compile(r"^\s{0,3}(?:#{1,4}\s*|\*\*|__)?\s*([^:\n*]{2,40}?)\s*(?:\*\*|__)?\s*[:\-–]?\s*$")
_SCORE_RE = re.compile(r"оценк[аи][^0-9]{0,10}(\d+(?:[.,]\d+)?)\s*(?:/\s*10)?", re.IGNORECASE)


def parse_report(text: str) -> ModelReport:
    """Extract a structured report from mentor output (best effort)."""
    report = ModelReport()
    body = text

    for match in _FENCE_RE.finditer(text):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        report.score = _score(payload.get("score"))
        report.reasoning = str(payload.get("reasoning") or payload.get("reasoning_text") or "")
        for key in ("strengths", "weaknesses", "risks", "recommendations"):
            items = payload.get(key)
            if isinstance(items, list):
                getattr(report, key).extend(str(item) for item in items if str(item).strip())
        body = text.replace(match.group(0), "").strip()
        break

    if report.is_empty() or not report.reasoning:
        _parse_sections(body, report)

    if report.score is None:
        score_match = _SCORE_RE.search(text)
        if score_match:
            report.score = _score(score_match.group(1))
    return report


def _score(value: object) -> float | None:
    try:
        score = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if 0 <= score <= 10:
        return score
    return None


def _parse_sections(text: str, report: ModelReport) -> None:
    current: str | None = None
    buffer: list[str] = []

    def flush():
        nonlocal buffer, current
        if current and buffer:
            content = "\n".join(buffer).strip()
            if current == "reasoning":
                if not report.reasoning:
                    report.reasoning = content
            else:
                items = [re.sub(r"^[-*•]\s*", "", line).strip()
                         for line in content.splitlines() if line.strip()]
                getattr(report, current).extend(item for item in items if item)
        buffer = []

    for line in text.splitlines():
        header_key = _match_header(line)
        if header_key:
            flush()
            current = header_key
            continue
        if current:
            buffer.append(line)
    flush()

    if report.is_empty():
        report.reasoning = text.strip()


def _match_header(line: str) -> str | None:
    match = _HEADER_RE.match(line)
    if not match:
        return None
    candidate = match.group(1).strip().lower().rstrip(":")
    for key, aliases in _SECTION_ALIASES.items():
        if candidate in aliases or any(alias in candidate for alias in aliases):
            return key
    return None


def report_to_markdown(report: ModelReport, title: str = "Оценка модели") -> str:
    lines = [f"# {title}", ""]
    if report.score is not None:
        lines += [f"**Оценка: {report.score:g}/10**", ""]
    if report.reasoning:
        lines += ["## Рассуждение", report.reasoning, ""]
    for caption, items in (
        ("Что хорошо", report.strengths),
        ("Что плохо", report.weaknesses),
        ("Риски", report.risks),
        ("Рекомендации", report.recommendations),
    ):
        if items:
            lines += [f"## {caption}"]
            lines += [f"- {item}" for item in items]
            lines += [""]
    return "\n".join(lines)


class ReportStore:
    """Stores the latest report plus a short history per app."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else (app_data_dir() / "reports")
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, report: ModelReport) -> Path:
        path = self.directory / f"report-{report.id}.json"
        path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        (self.directory / "latest.json").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8")
        return path

    def latest(self) -> ModelReport | None:
        path = self.directory / "latest.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ModelReport(**{
                key: value for key, value in raw.items()
                if key in ModelReport.__dataclass_fields__
            })
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def list(self, limit: int = 10) -> list[Path]:
        return sorted(self.directory.glob("report-*.json"), reverse=True)[:limit]
