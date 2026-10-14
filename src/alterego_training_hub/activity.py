"""Append-only activity feed: what the mentor, training and the app did."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import app_data_dir


@dataclass
class ActivityEvent:
    kind: str  # "training" | "mentor_tool" | "file_edit" | "report" | "system"
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)

    def stamp(self) -> str:
        return time.strftime("%d.%m %H:%M", time.localtime(self.created_at))


class ActivityLog:
    """JSONL log kept in the user's app-data folder (never in the repository)."""

    MAX_EVENTS = 500

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else (app_data_dir() / "activity.jsonl")

    def log(self, kind: str, summary: str, **details: Any) -> ActivityEvent:
        event = ActivityEvent(kind=str(kind), summary=str(summary)[:500],
                              details={k: v for k, v in details.items() if v is not None})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        self._trim()
        return event

    def _trim(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) > self.MAX_EVENTS * 1.2:
            self.path.write_text("\n".join(lines[-self.MAX_EVENTS:]) + "\n",
                                 encoding="utf-8")

    def recent(self, limit: int = 30, kind: str | None = None) -> list[ActivityEvent]:
        if not self.path.exists():
            return []
        events: list[ActivityEvent] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in reversed(lines[-400:]):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kind and raw.get("kind") != kind:
                continue
            try:
                events.append(ActivityEvent(**{
                    key: value for key, value in raw.items()
                    if key in ActivityEvent.__dataclass_fields__
                }))
            except TypeError:
                continue
            if len(events) >= limit:
                break
        return events
