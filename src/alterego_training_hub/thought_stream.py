"""Thought stream: structured «Мысль → Действие → Ответ» protocol.

Non-reasoning chat models can be instructed (see :data:`THOUGHT_SYSTEM_EXTRA`)
to answer in short labelled blocks.  This module parses those blocks back into
:class:`ThoughtStep` items so the UI can show *why* the agent answered the way
it did, and strips the protocol from the displayed answer text.

Pure logic — no tkinter, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

THOUGHT_SYSTEM_EXTRA = (
    "Когда отвечаешь непростой вопрос, мысли протоколируй короткими блоками "
    "в начале ответа:\n"
    "Мысль: <одна строка — что анализируешь>\n"
    "Действие: <одна строка — что делаешь или какие данные берёшь>\n"
    "(повтори блоки «Мысль»/«Действие» столько раз, сколько нужно, затем)\n"
    "Ответ: <итоговый ответ без протокола>\n"
    "Блоки должны быть короткими. Если вопрос простой — ответь сразу без блоков."
)

_LABELS = {"мысль": "thought", "thought": "thought",
           "действие": "action", "action": "action",
           "ответ": "answer", "answer": "answer"}

_LINE_RE = re.compile(
    r"^\s*(Мысль|Действие|Ответ|Thought|Action|Answer)\s*:\s*(.*)$",
    re.IGNORECASE)


@dataclass(frozen=True)
class ThoughtStep:
    """One step of a structured protocol block."""

    kind: str  # "thought" | "action" | "answer"
    text: str
    index: int = 0

    @property
    def mark(self) -> str:
        return {"thought": "💭", "action": "⚙", "answer": "💬"}.get(self.kind, "•")

    def line(self) -> str:
        labels = {"thought": "Мысль", "action": "Действие", "answer": "Ответ"}
        return f"{self.mark} {labels.get(self.kind, self.kind)}: {self.text.strip()}"


@dataclass
class ThoughtRecord:
    """Parsed protocol of one message: ordered steps + cleaned answer text."""

    steps: list[ThoughtStep] = field(default_factory=list)
    answer: str = ""

    @property
    def has_protocol(self) -> bool:
        return any(step.kind in ("thought", "action") for step in self.steps)

    def render(self) -> str:
        if not self.steps:
            return ""
        return "\n".join(step.line() for step in self.steps)


def parse_thought_block(text: str) -> ThoughtRecord:
    """Split a protocol-style reply into steps and the final answer.

    Unknown lines before the first label belong to the answer (the model may
    write a lead-in).  Lines after an «Ответ:» label are answer text.  With no
    labels at all the whole text is the answer and ``steps`` is empty.
    """
    record = ThoughtRecord()
    current_kind: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current_kind, buffer
        if current_kind is None:
            return
        body = "\n".join(buffer).strip()
        if current_kind == "answer":
            record.answer = body
        elif body:
            record.steps.append(
                ThoughtStep(kind=current_kind, text=body,
                            index=len(record.steps)))
        current_kind = None
        buffer = []

    for raw in (text or "").splitlines():
        match = _LINE_RE.match(raw)
        if match:
            flush()
            current_kind = _LABELS[match.group(1).lower()]
            buffer = [match.group(2)]
        elif current_kind is not None:
            buffer.append(raw)
        else:
            if raw.strip():
                if record.answer:
                    record.answer += "\n" + raw
                else:
                    record.answer = raw
    flush()
    if not record.answer:
        # No «Ответ:» block: keep a lead-in-free fallback of remaining lines.
        answer_steps = [s for s in record.steps if s.kind == "answer"]
        record.answer = answer_steps[0].text if answer_steps else ""
    return record


def render_thoughts(record: ThoughtRecord) -> str:
    """Human-readable protocol line list (empty when nothing was logged)."""
    return record.render()


def render_thoughts_or_hint(record: ThoughtRecord, *, hint: str = "") -> str:
    """Protocol text, or ``hint`` when the model did not use the protocol."""
    if record.has_protocol:
        return record.render()
    return hint
