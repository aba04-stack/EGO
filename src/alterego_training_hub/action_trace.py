"""Action trace: an auditable journal of every tool the agent executed.

Built from chat transcript/session messages (role="tool") or recorded live
from agent events, so the user can check *what the agent actually did* and ask
it to explain any step.

Pure logic — no tkinter, no network.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

_CLIP = 160


@dataclass(frozen=True)
class ActionEntry:
    """One executed tool call."""

    tool: str
    summary: str
    ok: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)
    why: str = ""
    at: float = 0.0

    def line(self) -> str:
        mark = "✓" if self.ok else "✗"
        summary = " ".join(self.summary.split())[:_CLIP]
        return f"{mark} {self.tool} — {summary}" if summary else f"{mark} {self.tool}"

    def detail(self) -> str:
        args = json.dumps(self.arguments, ensure_ascii=False)[:400] if self.arguments else "—"
        rows = [f"Инструмент: {self.tool}",
                f"Аргументы: {args}",
                f"Результат: {self.summary.strip() or '—'}",
                f"Статус: {'успех' if self.ok else 'ошибка'}"]
        if self.why:
            rows.insert(1, f"Зачем: {self.why}")
        return "\n".join(rows)


class ActionTrace:
    """In-memory journal of :class:`ActionEntry` items."""

    def __init__(self) -> None:
        self._entries: list[ActionEntry] = []

    def record(self, entry: ActionEntry) -> ActionEntry:
        self._entries.append(entry)
        return entry

    def record_tool(self, tool: str, summary: str, *, ok: bool = True,
                    arguments: Mapping[str, Any] | None = None,
                    why: str = "", at: float | None = None) -> ActionEntry:
        return self.record(ActionEntry(
            tool=str(tool), summary=str(summary), ok=bool(ok),
            arguments=dict(arguments or {}), why=str(why),
            at=float(time.time() if at is None else at)))

    def entries(self) -> list[ActionEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def render(self, limit: int = 20) -> str:
        rows = self._entries[-limit:] if limit else list(self._entries)
        if not rows:
            return ""
        return "\n".join(entry.line() for entry in rows)


def _summary_from_result(content: str) -> tuple[bool, str]:
    """Interpret a tool-result payload: returns (ok, human summary)."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return True, str(content)
    if not isinstance(data, dict):
        return True, str(data)
    ok = bool(data.get("ok", True))
    for key in ("summary", "error", "message", "text", "content", "output"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return ok, value.strip()
    clipped = json.dumps(data, ensure_ascii=False)
    return ok, clipped[:_CLIP]


def action_entries_from_messages(messages: Iterable[Any]) -> list[ActionEntry]:
    """Build entries from chat messages (ChatMessage or plain dicts).

    Only role="tool" items are recorded: each carries the tool ``name`` and a
    JSON result payload produced by :class:`~alterego_training_hub.agent.MentorAgent`.
    """
    entries: list[ActionEntry] = []
    for message in messages:
        role = getattr(message, "role", None)
        if role is None and isinstance(message, Mapping):
            role = message.get("role")
        if role != "tool":
            continue
        name = getattr(message, "name", "")
        if name == "" and isinstance(message, Mapping):
            name = message.get("name", "")
        content = getattr(message, "content", "")
        if content == "" and isinstance(message, Mapping):
            content = message.get("content", "")
        ok, summary = _summary_from_result(content)
        at = float(getattr(message, "created_at", 0.0) or 0.0)
        entries.append(ActionEntry(tool=str(name or "?"), summary=summary,
                                   ok=ok, at=at))
    return entries


def explain_prompt(entry: ActionEntry) -> str:
    """Question to send the agent to explain one recorded step."""
    args = json.dumps(entry.arguments, ensure_ascii=False) if entry.arguments else "—"
    return (f"Объясни одним-двумя предложениями, зачем ты вызвал инструмент "
            f"«{entry.tool}» с аргументами {args[:200]}. Что это давало "
            f"текущей цели?")
