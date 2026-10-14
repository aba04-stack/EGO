"""Night watch: periodic mentor check-ins during training and a morning sum.

The core is scheduler-free and side-effect light: ``due()`` decides when the
next check runs, ``run_check()`` asks the mentor to analyse one snapshot and
``morning_report()`` folds the night's entries into a summary. The desktop
shell drives it with a minute tick; the log persists as JSON.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

NIGHT_PROMPT = (
    "Ты — ночной дежурный инженер обучения. Проанализируй снимок метрик и "
    "журнал watchdog. Ответь кратко: (1) состояние обучения одной фразой, "
    "(2) риски/аномалии, (3) одно действие к утру. Без воды."
)


class NightWatchError(RuntimeError):
    """Night watch input error safe to display."""


@dataclass
class WatchConfig:
    enabled: bool = False
    start: str = "22:00"      # HH:MM, window may cross midnight
    end: str = "08:00"
    interval_minutes: int = 30

    def validate(self) -> None:
        for label, value in (("start", self.start), ("end", self.end)):
            if not _parse_hhmm(value):
                raise NightWatchError(f"Время {label}: формат ЧЧ:ММ.")
        try:
            interval = int(self.interval_minutes)
        except (TypeError, ValueError):
            raise NightWatchError("Интервал: целое число минут.") from None
        if not 5 <= interval <= 24 * 60:
            raise NightWatchError("Интервал: 5–1440 минут.")

    def in_window(self, now: float | None = None) -> bool:
        moment = time.localtime(now if now is not None else time.time())
        current = moment.tm_hour * 60 + moment.tm_min
        start = _parse_hhmm(self.start)
        end = _parse_hhmm(self.end)
        if start is None or end is None:
            return False
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end  # overnight window


@dataclass
class WatchEntry:
    at: float = field(default_factory=time.time)
    summary: str = ""
    issues: list[str] = field(default_factory=list)
    ok: bool = True

    def line(self) -> str:
        stamp = time.strftime("%H:%M", time.localtime(self.at))
        mark = "✓" if self.ok else "✗"
        issues = f" · {', '.join(self.issues[:3])}" if self.issues else ""
        return f"{stamp} {mark} {self.summary}{issues}"


def _parse_hhmm(text: str) -> int | None:
    try:
        hours, minutes = str(text or "").strip().split(":")
        hours, minutes = int(hours), int(minutes)
    except (TypeError, ValueError):
        return None
    if 0 <= hours <= 23 and 0 <= minutes <= 59:
        return hours * 60 + minutes
    return None


def due(last_run: float, now: float | None = None,
        interval_minutes: int = 30) -> bool:
    """True when ``interval_minutes`` elapsed since ``last_run``."""
    try:
        interval = max(5, int(interval_minutes))
    except (TypeError, ValueError):
        return False
    current = now if now is not None else time.time()
    return current - float(last_run or 0.0) >= interval * 60


class NightWatchLog:
    """Append-only JSON log of watch entries."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def entries(self) -> list[WatchEntry]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out: list[WatchEntry] = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict):
                out.append(WatchEntry(
                    at=float(item.get("at") or 0.0),
                    summary=str(item.get("summary") or ""),
                    issues=[str(x) for x in item.get("issues") or []],
                    ok=bool(item.get("ok", True))))
        return out

    def add(self, entry: WatchEntry) -> None:
        items = [asdict(item) for item in self.entries()]
        items.append(asdict(entry))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def clear(self) -> None:
        if self.path.is_file():
            self.path.unlink()


def run_check(mentor, *, tail: str, dashboard: str,
              issues: list[str] | None = None) -> WatchEntry:
    """Ask the mentor to analyse one snapshot; never raises."""
    problems = [str(item) for item in (issues or [])]
    prompt = [NIGHT_PROMPT, f"\nДашборд:\n{dashboard or '—'}",
              f"\nХвост лога:\n{(tail or '—')[-1500:]}"]
    if problems:
        prompt.append("\nПроблемы watchdog: " + "; ".join(problems[:8]))
    messages = [{"role": "user", "content": "\n".join(prompt)}]
    try:
        reply = mentor.respond(messages, tools=None, max_tokens=400,
                               temperature=0.2)
        text = str(getattr(reply, "text", "") or "").strip()
        return WatchEntry(summary=text.splitlines()[0][:200] if text
                          else "пустой ответ наставника",
                          issues=problems, ok=bool(text))
    except Exception as exc:  # noqa: BLE001 - overnight loop must survive
        return WatchEntry(summary=f"ошибка опроса: {type(exc).__name__}",
                          issues=problems + [str(exc)[:120]], ok=False)


def morning_report(entries: list[WatchEntry], *, title: str = "") -> str:
    """Fold night entries into one summary block."""
    items = list(entries or [])
    lines = [f"🌅 {title or 'Итог ночного дежурства'}"]
    if not items:
        lines.append("Ночных проверок не было.")
        return "\n".join(lines)
    good = sum(1 for item in items if item.ok)
    lines.append(f"Проверок: {len(items)} · успешных: {good} · "
                 f"с проблемами: {len(items) - good}")
    failed = [item for item in items if not item.ok]
    if failed:
        lines.append("События:")
        lines.extend(f"  {item.line()}" for item in failed[-5:])
    lines.append("Последнее наблюдение:")
    lines.append(f"  {items[-1].line()}")
    distinct = sorted({issue for item in items for issue in item.issues})
    if distinct:
        lines.append("Замечания за ночь:")
        lines.extend(f"  — {issue}" for issue in distinct[:8])
    return "\n".join(lines)


def config_to_dict(config: WatchConfig) -> dict[str, Any]:
    return asdict(config)


def config_from_dict(raw: dict[str, Any]) -> WatchConfig:
    config = WatchConfig(
        enabled=bool((raw or {}).get("enabled", False)),
        start=str((raw or {}).get("start") or "22:00"),
        end=str((raw or {}).get("end") or "08:00"),
        interval_minutes=int((raw or {}).get("interval_minutes") or 30))
    config.validate()
    return config
