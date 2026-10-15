"""Training watchdog: detect unhealthy training early and suggest fixes.

Pure logic (no UI, no I/O): the UI polls it while training runs and the
mentor can read the same issues through its tools.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .metrics import MetricsSummary

LOSS_SPIKE_RATIO = 3.0
RISING_STREAK = 3
PLATEAU_IMPROVEMENT = 1e-4
DEFAULT_QUIET_SECONDS = 90.0


@dataclass
class Issue:
    code: str
    severity: str  # "info" | "warn" | "crit"
    message: str
    suggestion: str = ""

    def line(self) -> str:
        mark = {"crit": "‼", "warn": "⚠", "info": "ℹ"}.get(self.severity, "·")
        text = f"{mark} {self.message}"
        if self.suggestion:
            text += f" → {self.suggestion}"
        return text


@dataclass
class WatchdogReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def worst(self) -> str:
        for level in ("crit", "warn", "info"):
            if any(issue.severity == level for issue in self.issues):
                return level
        return "ok"

    def lines(self) -> list[str]:
        return [issue.line() for issue in self.issues]


def _loss_values(summary: MetricsSummary) -> list[float]:
    return summary.series("loss")


def detect_issues(summary: MetricsSummary, *,
                  running: bool = False,
                  quiet_seconds: float = 0.0) -> list[Issue]:
    issues: list[Issue] = []
    losses = _loss_values(summary)

    if any("NaN" in item or "Inf" in item for item in summary.anomalies):
        issues.append(Issue(
            "nan", "crit", "NaN/Inf в метриках обучения",
            "уменьшите lr (set_training_control lr=...) и проверьте данные"))

    # Loss spike: last loss jumped several times above the previous one.
    if len(losses) >= 2:
        previous, last = losses[-2], losses[-1]
        if (not math.isnan(previous) and not math.isnan(last) and previous > 0
                and last > previous * LOSS_SPIKE_RATIO):
            issues.append(Issue(
                "spike", "warn", f"Всплеск loss: {previous:.3f} → {last:.3f}",
                "снизьте lr или добавьте clip-градиентов (grad_clip)"))

    # Rising streak: loss grows for several epochs in a row.
    if len(losses) >= RISING_STREAK:
        streak = all(losses[-i] > losses[-i - 1] for i in range(1, RISING_STREAK))
        if streak:
            issues.append(Issue(
                "rising", "warn",
                f"Loss растёт {RISING_STREAK} эпохи подряд",
                "lr слишком высок: умножьте на 0.3 (set_training_control lr=...)"))

    # Plateau: no meaningful improvement over the recent window.
    if len(losses) >= 5:
        window = losses[-5:]
        if window and (max(window) - min(window)) < PLATEAU_IMPROVEMENT:
            issues.append(Issue(
                "plateau", "info", "Loss не улучшается (плато)",
                "рассмотрите раннюю остановку (early_stop_patience) или другой lr"))

    # Stalled process: training is running but the log is quiet.
    if running and quiet_seconds >= DEFAULT_QUIET_SECONDS:
        issues.append(Issue(
            "stalled", "warn",
            f"Нет вывода обучения {int(quiet_seconds)} с",
            "проверьте процесс: возможно, обучение зависло (stop_training)"))

    # Progress overview while running.
    if running and summary.epochs_total and summary.epoch_current is not None:
        ratio = summary.progress_ratio or 0.0
        issues.append(Issue(
            "progress", "info",
            f"Эпоха {summary.epoch_current:g}/{summary.epochs_total} "
            f"({ratio:.0%})", ""))
    return issues


class TrainingWatchdog:
    """Stateful wrapper: reports each new issue once per training run."""

    def __init__(self, quiet_seconds: float = DEFAULT_QUIET_SECONDS):
        self.quiet_seconds = quiet_seconds
        self._seen: set[str] = set()
        self._last_report: WatchdogReport | None = None

    def reset(self) -> None:
        self._seen.clear()
        self._last_report = None

    def evaluate(self, summary: MetricsSummary, *,
                 running: bool = False,
                 quiet_seconds: float = 0.0) -> WatchdogReport:
        issues = detect_issues(summary, running=running,
                               quiet_seconds=quiet_seconds)
        fresh = [issue for issue in issues if issue.code not in self._seen]
        self._seen.update(issue.code for issue in fresh)
        self._last_report = WatchdogReport(issues=issues)
        return WatchdogReport(issues=fresh)

    @property
    def last_report(self) -> WatchdogReport | None:
        return self._last_report
