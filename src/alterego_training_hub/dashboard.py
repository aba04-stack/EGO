"""Chat metrics dashboards: compact Unicode report cards from summaries.

The dashboard is plain text with sparklines so it renders in the chat, the
terminal and exported transcripts alike — no charts library required.
"""
from __future__ import annotations

import math
from typing import Any

from .metrics import MetricsSummary

SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 24) -> str:
    """Unicode sparkline of the last ``width`` finite values."""
    clean = [float(v) for v in values
             if isinstance(v, (int, float)) and not math.isnan(v)][-int(width or 24):]
    if not clean:
        return "—"
    low, high = min(clean), max(clean)
    if high <= low:
        return SPARK_BLOCKS[0] * len(clean)
    step = (len(SPARK_BLOCKS) - 1) / (high - low)
    return "".join(
        SPARK_BLOCKS[int((value - low) * step)] for value in clean)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 1000 else f"{value:.1f}"
    return str(value)


def build_dashboard(summary: MetricsSummary, *, title: str = "",
                    extra: dict[str, Any] | None = None) -> str:
    """Render a text dashboard card for the chat."""
    lines = [f"📊 {title or 'Дашборд метрик'}"]
    if summary.epoch_current is not None:
        total = f"/{summary.epochs_total}" if summary.epochs_total else ""
        lines.append(f"Эпоха: {_fmt(summary.epoch_current)}{total} · "
                     f"шагов: {summary.steps_seen}")
    if not summary.last:
        lines.append("Метрик пока нет.")
        return "\n".join(lines)

    for key in sorted(summary.last):
        series = summary.series(key)
        trend = summary.trend.get(key, "")
        best = summary.best.get(key)
        row = f"{key}: {_fmt(summary.last[key])}"
        if best is not None and best != summary.last.get(key):
            row += f" (лучшее {_fmt(best)})"
        if trend:
            row += f" · {trend}"
        lines.append(row)
        if len(series) >= 2:
            lines.append("  " + sparkline(series))

    if summary.anomalies:
        lines.append("⚠ " + "; ".join(summary.anomalies[:5]))
    for name, value in dict(extra or {}).items():
        lines.append(f"{name}: {_fmt(value)}")
    return "\n".join(lines)
