"""Parse training logs into metric series, trends, progress and anomalies.

Understands common line formats printed by training scripts:
``loss=0.53 acc=0.81 lr=1e-4``, ``Epoch 3/10: loss: 0.42``, ``step 120 [340/1000]``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

PAIR_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9_\-]{0,30})\s*[:=]\s*"
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|nan|inf)"
)
EPOCH_RE = re.compile(r"epoch[^0-9]{0,6}(\d+(?:\.\d+)?)\s*/\s*(\d+)", re.IGNORECASE)
STEP_RE = re.compile(r"(?:step|iter|iteration)[^0-9]{0,6}(\d+)", re.IGNORECASE)
PROGRESS_RE = re.compile(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]")

EXCLUDED_KEYS = {
    "epoch", "epochs", "step", "steps", "iter", "iteration", "batch", "bs",
    "it", "s", "time", "total", "mem", "vram", "gpu", "rank", "world", "size",
    "percent", "pct", "eta", "elapsed", "acc_step", "global",
}
EXCLUDED_KEY_SUBSTRINGS = ("time", "per_", "/s", "s/", "percent", "pct")

LOSS_KEYS = ("val_loss", "eval_loss", "valid_loss", "train_loss", "loss", "total_loss")
HIGHER_BETTER_KEYS = {
    "acc", "accuracy", "val_acc", "val_accuracy", "eval_acc", "f1", "bleu",
    "rouge", "reward", "score", "precision", "recall", "exact_match", "em",
}


@dataclass
class MetricPoint:
    step: int
    epoch: float | None
    values: dict[str, float] = field(default_factory=dict)
    line_no: int = 0


@dataclass
class MetricsSummary:
    points: list[MetricPoint] = field(default_factory=list)
    last: dict[str, float] = field(default_factory=dict)
    best: dict[str, float] = field(default_factory=dict)
    trend: dict[str, str] = field(default_factory=dict)  # key -> verdict
    anomalies: list[str] = field(default_factory=list)
    epoch_current: float | None = None
    epochs_total: int | None = None
    steps_seen: int = 0

    @property
    def primary_key(self) -> str | None:
        for key in LOSS_KEYS:
            if key in self.last:
                return key
        return next(iter(self.last), None)

    @property
    def progress_ratio(self) -> float | None:
        if self.epoch_current is not None and self.epochs_total:
            return max(0.0, min(1.0, self.epoch_current / self.epochs_total))
        return None

    def series(self, key: str) -> list[float]:
        return [point.values[key] for point in self.points if key in point.values]


def _clean_key(key: str) -> str:
    return key.strip().lower()


def _valid_key(key: str) -> bool:
    if not key or key in EXCLUDED_KEYS:
        return False
    return not any(part in key for part in EXCLUDED_KEY_SUBSTRINGS)


def _to_float(raw: str) -> float | None:
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_log(text: str) -> MetricsSummary:
    summary = MetricsSummary()
    step = 0
    current_epoch: float | None = None
    epochs_total: int | None = None
    nan_lines: list[int] = []

    for line_no, line in enumerate(text.splitlines(), 1):
        epoch_match = EPOCH_RE.search(line)
        if epoch_match:
            current_epoch = float(epoch_match.group(1))
            epochs_total = int(epoch_match.group(2))
        if re.search(r"\b(?:nan|inf|[-+]?inf)\b", line, re.IGNORECASE):
            if PAIR_RE.search(line):
                nan_lines.append(line_no)

        step_match = STEP_RE.search(line) or PROGRESS_RE.search(line)
        if step_match:
            try:
                step = max(step, int(step_match.group(1)))
            except (ValueError, IndexError):
                pass

        values: dict[str, float] = {}
        for key, raw in PAIR_RE.findall(line):
            key = _clean_key(key)
            if not _valid_key(key):
                continue
            value = _to_float(raw)
            if value is None:
                continue
            values[key] = value
        if not values:
            continue
        step += 1
        summary.points.append(
            MetricPoint(step=step, epoch=current_epoch, values=values, line_no=line_no)
        )

    summary.epoch_current = current_epoch
    summary.epochs_total = epochs_total
    summary.steps_seen = step

    if summary.points:
        summary.last = dict(summary.points[-1].values)
        for point in summary.points:
            for key, value in point.values.items():
                if key not in summary.best:
                    summary.best[key] = value
                elif key in HIGHER_BETTER_KEYS or key.startswith("val_") and "acc" in key:
                    summary.best[key] = max(summary.best[key], value)
                elif "loss" in key:
                    summary.best[key] = min(summary.best[key], value)
                else:
                    summary.best[key] = value  # neutral: keep latest-known extreme min/max loosely
        summary.trend = _trends(summary)
        summary.anomalies = _anomalies(summary, nan_lines)

    for line_no in nan_lines[:5]:
        summary.anomalies.append(f"NaN/Inf в логе (строка {line_no}) — проверьте численную стабильность.")
    return summary


def _trends(summary: MetricsSummary) -> dict[str, str]:
    trends: dict[str, str] = {}
    keys = [k for k in (summary.primary_key,) if k]
    keys += [k for k in summary.last if k not in keys][:2]
    count = len(summary.points)
    window = max(1, count // 3)
    for key in keys:
        values = summary.series(key)
        if len(values) < 4:
            trends[key] = "мало данных"
            continue
        head = sum(values[:window]) / window
        tail = sum(values[-window:]) / window
        delta = tail - head
        scale = max(abs(head), 1e-9)
        relative = abs(delta) / scale
        if relative < 0.02:
            trends[key] = "стабильно"
        elif (delta < 0) == (key not in HIGHER_BETTER_KEYS):
            trends[key] = "улучшается"
        else:
            trends[key] = "ухудшается"
    return trends


def _anomalies(summary: MetricsSummary, nan_lines: list[int]) -> list[str]:
    anomalies: list[str] = []
    key = summary.primary_key
    if key:
        values = summary.series(key)
        if values:
            if values[-1] > values[0] * 1.25 and values[-1] > 0:
                anomalies.append(
                    f"«{key}» вырос с {values[0]:.4g} до {values[-1]:.4g} — возможна расходимость."
                )
            best = summary.best.get(key, values[-1])
            if "loss" in key and best > 0 and values[-1] > best * 1.6:
                anomalies.append(
                    f"«{key}» сейчас ({values[-1]:.4g}) заметно хуже лучшего ({best:.4g})."
                )
            if len(values) >= 6 and max(values[-6:]) - min(values[-6:]) < 1e-12:
                anomalies.append(f"«{key}» не меняется последние 6 замеров — стагнация.")
    if summary.epoch_current is not None and summary.epochs_total:
        if summary.epoch_current > summary.epochs_total:
            anomalies.append("Текущая эпоха превышает заявленное количество эпох.")
    return anomalies


def brief(summary: MetricsSummary) -> str:
    """One-line human summary for status bars and chat prompts."""
    if not summary.last:
        return "метрик в логе пока нет"
    key = summary.primary_key or next(iter(summary.last))
    parts = [f"{name}: {value:.4g}" for name, value in list(summary.last.items())[:4]]
    trend = summary.trend.get(key, "")
    epoch = ""
    if summary.epoch_current is not None:
        total = f"/{summary.epochs_total}" if summary.epochs_total else ""
        epoch = f"эпоха {summary.epoch_current:g}{total} · "
    return epoch + " · ".join(parts) + (f" · тренд: {trend}" if trend else "")
