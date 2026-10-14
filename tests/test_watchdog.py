"""Tests for the training watchdog detectors (pure logic)."""
from __future__ import annotations

from alterego_training_hub.metrics import MetricsSummary, MetricPoint
from alterego_training_hub.watchdog import (
    DEFAULT_QUIET_SECONDS,
    TrainingWatchdog,
    detect_issues,
)


def _summary(losses, **kwargs) -> MetricsSummary:
    points = [MetricPoint(step=index, epoch=index + 1,
                          values={"loss": value, "acc": 0.1 * index})
              for index, value in enumerate(losses)]
    summary = MetricsSummary(points=points, last=dict(points[-1].values),
                             epoch_current=len(losses), epochs_total=10)
    for key, value in kwargs.items():
        setattr(summary, key, value)
    return summary


def _codes(issues):
    return {issue.code for issue in issues}


def test_detects_spike_rising_and_plateau():
    assert "spike" in _codes(detect_issues(_summary([1.0, 0.8, 5.0])))
    assert "rising" in _codes(detect_issues(_summary([1.0, 1.1, 1.2, 1.3])))
    assert "plateau" in _codes(detect_issues(_summary([1.0, 1.0, 1.0, 1.0, 1.0])))
    healthy = detect_issues(_summary([1.0, 0.8, 0.6, 0.5, 0.45]))
    assert _codes(healthy) <= {"progress"}  # nothing unhealthy


def test_detects_nan_and_stall():
    issues = detect_issues(_summary([1.0, 0.5], anomalies=[
        "NaN/Inf в логе (строка 3) — проверьте численную стабильность."]))
    assert "nan" in _codes(issues)
    assert any(issue.severity == "crit" for issue in issues)
    issues = detect_issues(_summary([1.0, 0.5]), running=True,
                           quiet_seconds=DEFAULT_QUIET_SECONDS + 10)
    assert "stalled" in _codes(issues)
    assert "progress" in _codes(issues)


def test_watchdog_reports_each_issue_once():
    watchdog = TrainingWatchdog()
    summary = _summary([1.0, 1.1, 1.2, 1.3])
    first = watchdog.evaluate(summary)
    assert _codes(first.issues) == {"rising"}
    second = watchdog.evaluate(summary)  # same state: no duplicate alerts
    assert second.issues == []
    watchdog.reset()
    third = watchdog.evaluate(summary)
    assert _codes(third.issues) == {"rising"}
    assert watchdog.last_report is not None


def test_issue_line_includes_suggestion():
    issues = detect_issues(_summary([1.0, 0.8, 5.0]))
    line = next(issue.line() for issue in issues if issue.code == "spike")
    assert "→" in line and "lr" in line
