"""A/B comparison of training runs: verdicts and overlay-ready series."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .metrics import MetricsSummary


@dataclass
class ComparisonReport:
    label_a: str = "A"
    label_b: str = "B"
    final_loss_a: float = float("nan")
    final_loss_b: float = float("nan")
    best_loss_a: float = float("nan")
    best_loss_b: float = float("nan")
    converge_a: int | None = None  # first epoch close to its own best loss
    converge_b: int | None = None
    winner: str = ""  # "a" | "b" | "tie" | ""
    verdict: str = ""
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [
            f"{self.label_a}: best loss={_fmt(self.best_loss_a)}, "
            f"final loss={_fmt(self.final_loss_a)}, "
            f"сошлась к эпохе {self.converge_a or '—'}",
            f"{self.label_b}: best loss={_fmt(self.best_loss_b)}, "
            f"final loss={_fmt(self.final_loss_b)}, "
            f"сошлась к эпохе {self.converge_b or '—'}",
        ]
        out.extend(self.notes)
        if self.verdict:
            out.append(self.verdict)
        return out


def _fmt(value: float) -> str:
    return f"{value:.4f}" if not math.isnan(value) else "—"


def _final_loss(summary: MetricsSummary) -> float:
    for key in ("loss", "train_loss", "val_loss"):
        values = summary.series(key)
        if values:
            return values[-1]
    return float("nan")


def _best_loss(summary: MetricsSummary) -> float:
    values = [value for key in ("loss", "train_loss", "val_loss")
              for value in summary.series(key)]
    values += list(summary.best.values())
    finite = [value for value in values if not math.isnan(value)]
    return min(finite) if finite else float("nan")


def _converge_epoch(summary: MetricsSummary, target: float) -> int | None:
    """First epoch whose loss reaches the shared target level."""
    if math.isnan(target):
        return None
    for key in ("loss", "val_loss", "train_loss"):
        values = summary.series(key)
        if values:
            for index, value in enumerate(values, start=1):
                if not math.isnan(value) and value <= target:
                    return index
            break
    return None


def compare_runs(a: MetricsSummary, b: MetricsSummary, *,
                 label_a: str = "A", label_b: str = "B") -> ComparisonReport:
    """Compare two runs on loss quality and convergence speed."""
    report = ComparisonReport(label_a=label_a, label_b=label_b)
    report.final_loss_a, report.final_loss_b = _final_loss(a), _final_loss(b)
    report.best_loss_a, report.best_loss_b = _best_loss(a), _best_loss(b)
    target = min(report.best_loss_a, report.best_loss_b) * 1.25
    report.converge_a, report.converge_b = _converge_epoch(a, target), \
        _converge_epoch(b, target)

    score_a = score_b = 0
    if report.best_loss_a == report.best_loss_a and report.best_loss_b == report.best_loss_b:
        if report.best_loss_a < report.best_loss_b * 0.97:
            score_a += 1
            report.notes.append(f"{label_a} лучше по минимальному loss.")
        elif report.best_loss_b < report.best_loss_a * 0.97:
            score_b += 1
            report.notes.append(f"{label_b} лучше по минимальному loss.")
    if report.converge_a is not None and report.converge_b is not None:
        if report.converge_a < report.converge_b:
            score_a += 1
            report.notes.append(f"{label_a} сошлась быстрее.")
        elif report.converge_b < report.converge_a:
            score_b += 1
            report.notes.append(f"{label_b} сошлась быстрее.")

    if score_a > score_b:
        report.winner, report.verdict = "a", f"Победитель: {label_a}."
    elif score_b > score_a:
        report.winner, report.verdict = "b", f"Победитель: {label_b}."
    elif report.best_loss_a == report.best_loss_a or report.best_loss_b == report.best_loss_b:
        report.winner, report.verdict = "tie", "Запуски сопоставимы по качеству."
    else:
        report.verdict = "Недостаточно метрик для сравнения."
    return report


def overlay_series(key: str, a: MetricsSummary, b: MetricsSummary, *,
                   label_a: str = "A", label_b: str = "B") -> dict[str, list[float]]:
    """Series dict ready for ``draw_line_chart`` (loss/acc overlay)."""
    return {label_a: a.series(key), label_b: b.series(key)}
