"""Self-critique: a second, read-only pass that checks an answer before the
user trusts it.

The critic receives the question, the answer and the evidence (tool results,
metrics, file snippets) and must respond with a strict verdict block::

    ВЕРДИКТ: ок | сомнительно
    УВЕРЕННОСТЬ: 0..1
    ПРОБЛЕМЫ: <одна строка; «—» если нет>

The parser is tolerant; :func:`run_critic` never raises — an error becomes a
«suspect» report with the error text.

Pure logic (the network call is injected as ``mentor``) — no tkinter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

CRITIQUE_PROMPT = (
    "Ты — критик ответов ИИ. Твоя задача — сверить ответ ассистента с фактами "
    "из доказательств (файлы, выводы команд, метрики): вымышленные или "
    "противоречащие утверждения должны быть помечены. Не придумывай новые "
    "факты. Ответь СТРОГО в формате:\n"
    "ВЕРДИКТ: ок\n"
    "УВЕРЕННОСТЬ: 0.85\n"
    "ПРОБЛЕМЫ: —\n"
    "(или ВЕРДИКТ: сомнительно и перечисли проблемы одной строкой)"
)

_VERDICT_RE = re.compile(r"^\s*ВЕРДИКТ\s*:\s*(ок|сомнительно|ok|suspect)\s*$",
                         re.IGNORECASE | re.MULTILINE)
_CONF_RE = re.compile(r"^\s*УВЕРЕННОСТЬ\s*:\s*([0-9]*[.,]?[0-9]+)\s*$",
                      re.IGNORECASE | re.MULTILINE)
_ISSUES_RE = re.compile(r"^\s*ПРОБЛЕМЫ\s*:\s*(.*)$", re.IGNORECASE | re.MULTILINE)


@dataclass
class CritiqueReport:
    """Verdict of one critic pass."""

    verdict: str = "ok"  # "ok" | "suspect"
    confidence: float = 0.0
    issues: tuple[str, ...] = ()
    text: str = ""

    @property
    def suspect(self) -> bool:
        return self.verdict != "ok"

    def flag(self) -> str:
        return "⚠ проверить" if self.suspect else "✓ без замечаний"

    def render(self) -> str:
        rows = [f"Вердикт: {self.flag()}",
                f"Уверенность: {self.confidence:.2f}"]
        if self.issues:
            rows.append("Проблемы: " + "; ".join(self.issues))
        if self.text and self.suspect:
            rows.append("")
            rows.append(self.text.strip()[:1200])
        return "\n".join(rows)


def parse_critique(text: str) -> CritiqueReport:
    """Parse the strict verdict block; tolerant to case and missing fields."""
    raw = text or ""
    verdict = "suspect"
    match = _VERDICT_RE.search(raw)
    if match:
        verdict = "ok" if match.group(1).lower() in {"ок", "ok"} else "suspect"
    confidence = 0.0
    conf_match = _CONF_RE.search(raw)
    if conf_match:
        try:
            confidence = max(0.0, min(1.0,
                                      float(conf_match.group(1).replace(",", "."))))
        except ValueError:
            confidence = 0.0
    issues: tuple[str, ...] = ()
    issues_match = _ISSUES_RE.search(raw)
    if issues_match:
        body = issues_match.group(1).strip()
        if body and body not in {"—", "-", "нет"}:
            issues = tuple(part.strip() for part in re.split(r"[;.]", body)
                           if part.strip())
    return CritiqueReport(verdict=verdict, confidence=confidence,
                          issues=issues, text=raw)


def build_critic_messages(*, question: str, answer: str,
                          evidence: str = "") -> list[dict[str, Any]]:
    """Messages for the critic call (system prompt + one user block)."""
    parts = []
    if question.strip():
        parts.append(f"Вопрос пользователя:\n{question.strip()[:2000]}")
    parts.append(f"Ответ ассистента:\n{(answer or '').strip()[:4000]}")
    if evidence.strip():
        parts.append(f"Доказательства (файлы/метрики/выводы):\n{evidence.strip()[:4000]}")
    else:
        parts.append("Доказательства: не предоставлены — проверяй только "
                     "внутреннюю согласованность ответа.")
    return [{"role": "system", "content": CRITIQUE_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)}]


def run_critic(mentor: Any, *, question: str = "", answer: str,
               evidence: str = "") -> CritiqueReport:
    """Run one critic pass.  Never raises: errors become a suspect report."""
    messages = build_critic_messages(question=question, answer=answer,
                                     evidence=evidence)
    try:
        reply = mentor.respond(messages, tools=None, max_tokens=400,
                               temperature=0.0)
        text = getattr(reply, "text", "") or ""
    except Exception as exc:
        return CritiqueReport(verdict="suspect", confidence=0.0,
                              issues=(f"ошибка проверки: {exc}",),
                              text=str(exc))
    report = parse_critique(text)
    if not report.issues and report.suspect:
        # No explicit problems listed — keep at least a marker.
        report = CritiqueReport(verdict=report.verdict,
                                confidence=report.confidence,
                                issues=report.issues or ("причина не указана",),
                                text=report.text)
    return report
