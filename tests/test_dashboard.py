"""Tests for chat metrics dashboards."""
from __future__ import annotations

from alterego_training_hub.dashboard import build_dashboard, sparkline
from alterego_training_hub.metrics import MetricPoint, MetricsSummary


def _summary() -> MetricsSummary:
    values = [3.0, 2.2, 1.6, 1.1, 0.8, 0.55]
    points = [MetricPoint(step=i + 1, epoch=i + 1,
                          values={"loss": v, "val_loss": v + 0.1,
                                  "acc": 1.0 - v / 4})
              for i, v in enumerate(values)]
    return MetricsSummary(points=points, last=dict(points[-1].values),
                          best={"loss": 0.55, "val_loss": 0.65, "acc": 0.86},
                          trend={"loss": "снижается"},
                          anomalies=["спайк на шаге 2"],
                          epoch_current=6, epochs_total=10, steps_seen=6)


def test_sparkline_shapes():
    assert sparkline([]) == "—"
    assert sparkline([1.0, 1.0, 1.0]) == "▁▁▁"
    line = sparkline([0.0, 1.0, 2.0, 3.0])
    assert len(line) == 4 and line[0] == "▁" and line[-1] == "█"
    assert len(sparkline(list(range(100)), width=10)) == 10


def test_build_dashboard_renders_keys_and_sparkline():
    text = build_dashboard(_summary(), title="Обучение demo")
    assert "📊 Обучение demo" in text
    assert "Эпоха: 6/10" in text
    assert "loss: 0.5500" in text
    assert "снижается" in text
    assert "спайк на шаге 2" in text
    assert "▁" in text  # sparkline rows present
    assert "лучшее" in text


def test_build_dashboard_empty_and_extra():
    text = build_dashboard(MetricsSummary())
    assert "Метрик пока нет" in text
    text = build_dashboard(_summary(), extra={"GPU": "A4000"})
    assert "GPU: A4000" in text
