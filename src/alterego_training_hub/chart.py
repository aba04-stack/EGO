"""Pure chart math for metric plots (no tkinter): points, scales, ticks.

The UI draws the result on a ``tkinter.Canvas``; everything that can be
tested without a display lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

CHART_PAD = 8.0


@dataclass
class SeriesView:
    """One plottable series with its own value range."""

    name: str
    values: list[float] = field(default_factory=list)
    color: str = "#2a7"


def _valid(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number and number not in (float("inf"), float("-inf")):
            out.append(number)
    return out


def value_range(series: Sequence[SeriesView]) -> tuple[float, float]:
    """Shared y-range across series; constant data gets a symmetric window."""
    values = [value for view in series for value in _valid(view.values)]
    if not values:
        return 0.0, 1.0
    low, high = min(values), max(values)
    if low == high:
        pad = abs(low) * 0.1 or 1.0
        return low - pad, high + pad
    span = high - low
    return low - span * 0.05, high + span * 0.05


def chart_points(values: Sequence[float], width: float, height: float, *,
                 vmin: float | None = None, vmax: float | None = None,
                 pad: float = CHART_PAD) -> list[tuple[float, float]]:
    """Map values to canvas coordinates (y grows downward, 0 at the top)."""
    data = _valid(values)
    if not data or width <= 2 * pad or height <= 2 * pad:
        return []
    if vmin is None or vmax is None:
        vmin, vmax = (min(data), max(data))
        if vmin == vmax:
            vmin, vmax = vmin - 1.0, vmax + 1.0
    if vmax <= vmin:
        vmin, vmax = vmin, vmin + 1.0
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    step = inner_w / max(1, len(data) - 1)
    points: list[tuple[float, float]] = []
    for index, value in enumerate(data):
        ratio = (value - vmin) / (vmax - vmin)
        points.append((pad + index * step, height - pad - ratio * inner_h))
    return points


def nice_ticks(vmin: float, vmax: float, count: int = 5) -> list[float]:
    """Readable axis ticks between vmin and vmax."""
    if vmax <= vmin or count < 2:
        return [vmin, vmax]
    span = vmax - vmin
    raw = span / (count - 1)
    magnitude = 1.0
    while raw / magnitude >= 10:
        magnitude *= 10
    while raw / magnitude < 1:
        magnitude /= 10
    fraction = raw / magnitude
    if fraction <= 1:
        step = magnitude
    elif fraction <= 2:
        step = 2 * magnitude
    elif fraction <= 5:
        step = 5 * magnitude
    else:
        step = 10 * magnitude
    ticks: list[float] = []
    current = step * round(vmin / step)
    while current <= vmax + step * 1e-9:
        if current >= vmin - step * 1e-9:
            ticks.append(round(current, 10))
        current += step
    return ticks or [vmin, vmax]


def format_tick(value: float) -> str:
    if abs(value) >= 100 or value == int(value):
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")
