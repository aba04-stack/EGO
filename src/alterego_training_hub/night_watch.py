"""Night watch: periodic mentor check-ins during training and a morning sum.

The core is scheduler-free and side-effect light: ``due()`` decides when the
next check runs, ``run_check()`` asks the mentor to analyse one snapshot and
``morning_report()`` folds the night's entries into a summary. The desktop
shell drives it with a minute tick; the log persists as JSON.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
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
        raw_hours, raw_minutes = str(text or "").strip().split(":")
        hours, minutes = int(raw_hours), int(raw_minutes)
    except (TypeError, ValueError):
        return None
    if 0 <= hours <= 23 and 0 <= minutes <= 59:
        return hours * 60 + minutes
    return None


def due(last_run: float, now: float | None = None,
        interval_minutes: int = 30) -> bool:
    """True when interval_minutes elapsed; malformed saved times fail safe."""
    try:
        interval = max(5, int(interval_minutes))
    except (TypeError, ValueError, OverflowError):
        return False
    try:
        current = float(now if now is not None else time.time())
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(current):
        return False
    try:
        last = float(last_run or 0.0)
    except (TypeError, ValueError, OverflowError):
        last = 0.0
    if not math.isfinite(last):
        last = 0.0
    # An invalid last-run timestamp should not permanently suppress the watch.
    return current - last >= interval * 60


def _backup_corrupt_file(path: Path) -> Path | None:
    """Copy a corrupt file to a timestamped backup using an atomic replace."""
    if not path.is_file():
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None

    backup = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{backup.name}.", suffix=".tmp", dir=str(path.parent))
        temporary_path = Path(name)
        stream = os.fdopen(descriptor, "wb")
        descriptor = None
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, backup)
        return backup
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
        return None


class NightWatchLog:
    """Append-only JSON log of watch entries, with safe recovery from corruption."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.load_error = ""
        self._corrupt_backed_up = False

    def _backup_corrupt(self) -> bool:
        """Preserve a damaged original at most once per log instance."""
        if self._corrupt_backed_up:
            return True
        self._corrupt_backed_up = _backup_corrupt_file(self.path) is not None
        return self._corrupt_backed_up

    def entries(self) -> list[WatchEntry]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            backed_up = self._backup_corrupt()
            detail = ("исходный файл сохранён в резервной копии."
                      if backed_up else "резервную копию создать не удалось.")
            self.load_error = f"Журнал повреждён; {detail}"
            return []
        except OSError as exc:
            self.load_error = f"Не удалось прочитать журнал ({type(exc).__name__})."
            return []
        if not isinstance(raw, list):
            backed_up = self._backup_corrupt()
            detail = ("исходный файл сохранён в резервной копии."
                      if backed_up else "резервную копию создать не удалось.")
            self.load_error = f"Формат журнала повреждён; {detail}"
            return []

        out: list[WatchEntry] = []
        skipped = 0
        for item in raw:
            if not isinstance(item, dict):
                skipped += 1
                continue
            try:
                stamp = float(item.get("at") or 0.0)
            except (TypeError, ValueError, OverflowError):
                skipped += 1
                continue
            if not math.isfinite(stamp):
                skipped += 1
                continue

            raw_issues = item.get("issues", [])
            if isinstance(raw_issues, list):
                issues = [str(value) for value in raw_issues]
            elif raw_issues in (None, ""):
                issues = []
            else:
                # Keep the rest of this entry even if one field is malformed.
                issues = [str(raw_issues)]
                skipped += 1
            raw_ok = item.get("ok", True)
            if isinstance(raw_ok, bool):
                ok = raw_ok
            else:
                # Unknown status must never be interpreted as a successful check.
                ok = False
                skipped += 1
            out.append(WatchEntry(
                at=stamp,
                summary=str(item.get("summary") or ""),
                issues=issues,
                ok=ok,
            ))
        if skipped:
            backed_up = self._backup_corrupt()
            detail = ("исходный файл сохранён в резервной копии."
                      if backed_up else "резервную копию создать не удалось.")
            self.load_error = (
                f"В журнале обнаружены некорректные записи/поля: {skipped}; "
                f"{detail}"
            )
        else:
            self.load_error = ""
        return out

    def add(self, entry: WatchEntry) -> None:
        items = [asdict(item) for item in self.entries()]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            fd, name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp",
                dir=str(self.path.parent))
            temporary_path = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump([*items, asdict(entry)], stream,
                          ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        except BaseException:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            raise

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
    except Exception as exc:
        return WatchEntry(summary=f"ошибка опроса: {type(exc).__name__}",
                          issues=[*problems, str(exc)[:120]], ok=False)


def morning_report(entries: list[WatchEntry], *, title: str = "",
                   actions: list | None = None) -> str:
    """Fold night entries into one summary block.

    ``actions`` (optional :class:`~alterego_training_hub.action_trace.ActionEntry`
    items) appends a «Действия агента за ночь» section so the morning summary
    links to what the agent actually did, not just what it concluded.
    """
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
    if actions:
        lines.append("Действия агента за ночь:")
        lines.extend(f"  {entry.line()}" for entry in list(actions)[-8:])
    return "\n".join(lines)


def config_to_dict(config: WatchConfig) -> dict[str, Any]:
    return asdict(config)


def config_from_dict(raw: dict[str, Any]) -> WatchConfig:
    values = raw if isinstance(raw, dict) else {}
    interval_raw = values.get("interval_minutes", 30)
    if interval_raw is None or interval_raw == "":
        interval_raw = 30
    if isinstance(interval_raw, bool):
        raise NightWatchError("Интервал: целое число минут.")
    try:
        interval = int(interval_raw)
        if isinstance(interval_raw, float) and not interval_raw.is_integer():
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise NightWatchError("Интервал: целое число минут.") from None

    enabled_raw = values.get("enabled", False)
    config = WatchConfig(
        enabled=enabled_raw if isinstance(enabled_raw, bool) else False,
        start=str(values.get("start") or "22:00"),
        end=str(values.get("end") or "08:00"),
        interval_minutes=interval,
    )
    config.validate()
    return config



# ------------------------------------------------- верификатор обучения (этап 38)
@dataclass
class WatchState:
    """Previous night snapshot: samples + best val_loss for degradation diff."""

    samples: list[dict[str, Any]] = field(default_factory=list)
    best_val_loss: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"samples": list(self.samples),
                "best_val_loss": self.best_val_loss}

    @classmethod
    def from_dict(cls, raw: Any) -> WatchState:
        if not isinstance(raw, dict):
            return cls()
        raw_samples = raw.get("samples")
        samples = (
            [item for item in raw_samples if isinstance(item, dict)]
            if isinstance(raw_samples, list) else []
        )
        best = raw.get("best_val_loss")
        try:
            best_value = float(best) if isinstance(best, (int, float)) else None
        except (TypeError, ValueError, OverflowError):
            best_value = None
        if best_value is not None and not math.isfinite(best_value):
            best_value = None
        return cls(samples=samples, best_val_loss=best_value)


def _state_payload_needs_backup(raw: Any) -> bool:
    """Identify state payloads whose malformed fields would be discarded."""
    if not isinstance(raw, dict):
        return True
    samples = raw.get("samples", [])
    if not isinstance(samples, list) or any(
            not isinstance(item, dict) for item in samples):
        return True
    best = raw.get("best_val_loss")
    if best is not None:
        if isinstance(best, bool) or not isinstance(best, (int, float)):
            return True
        try:
            if not math.isfinite(float(best)):
                return True
        except (TypeError, ValueError, OverflowError):
            return True
    return False


def load_state(path: str | Path) -> WatchState:
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        _backup_corrupt_file(target)
        return WatchState()
    if _state_payload_needs_backup(raw):
        _backup_corrupt_file(target)
    return WatchState.from_dict(raw)


def save_state(path: str | Path, state: WatchState) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        fd, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        temporary_path = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state.to_dict(), stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
    except BaseException:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
        raise
    return target

def state_from_tail(tail: str) -> WatchState:
    """Snapshot (samples + best val_loss) from a training log tail."""
    from .evaluation import build_eval_report
    from .gen_preview import parse_samples

    samples = parse_samples(tail or "")
    report = build_eval_report(tail or "")
    return WatchState(
        samples=[{"step": s.step, "prompt": s.prompt, "text": s.text,
                  "checkpoint": s.checkpoint} for s in samples[-3:]],
        best_val_loss=report.best_val_loss)


def degradation_issues(previous: WatchState, current: WatchState) -> list[str]:
    """Compare two snapshots; human issues when generation quality drops."""
    issues: list[str] = []
    prev_best, cur_best = previous.best_val_loss, current.best_val_loss
    if (prev_best not in (None, 0) and cur_best is not None
            and cur_best > prev_best * 1.2):
        issues.append(
            f"Деградация: лучший val_loss ухудшился {prev_best:.3f} → "
            f"{cur_best:.3f} (+{(cur_best / prev_best - 1) * 100:.0f}%).")
    prev_texts = [str(s.get("text", "")).strip()
                  for s in previous.samples if isinstance(s, dict)]
    cur_texts = [str(s.get("text", "")).strip()
                 for s in current.samples if isinstance(s, dict)]
    if prev_texts and cur_texts:
        if not cur_texts[-1] and prev_texts[-1]:
            issues.append("Деградация: последний сэмпл генерации пуст, "
                          "раньше модель генерировала текст.")
        elif cur_texts[-1] and cur_texts[-1] == prev_texts[-1]:
            issues.append("Сэмплы генерации повторяются дословно между "
                          "проверками — похоже на зацикливание генерации.")
        elif prev_texts[-1] and len(cur_texts[-1]) < 0.3 * len(prev_texts[-1]):
            issues.append("Сэмплы генерации стали заметно короче "
                          f"({len(prev_texts[-1])} → {len(cur_texts[-1])} симв.).")
    return issues
