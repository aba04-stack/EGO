"""Tests for A/B run comparison and hyperparameter suggestions."""
from __future__ import annotations

from alterego_training_hub.compare import compare_runs, overlay_series
from alterego_training_hub.hparam_tuning import apply_suggestions, suggest_fixes
from alterego_training_hub.metrics import MetricPoint, MetricsSummary


def _summary(losses, val_losses=None) -> MetricsSummary:
    points = []
    for index, value in enumerate(losses):
        values = {"loss": value, "acc": min(0.99, 1.0 - value / 4)}
        if val_losses is not None:
            values["val_loss"] = val_losses[index]
        points.append(MetricPoint(step=index + 1, epoch=index + 1,
                                  values=values))
    return MetricsSummary(points=points, last=dict(points[-1].values),
                          epoch_current=len(losses), epochs_total=len(losses))


def test_compare_runs_picks_the_better_run():
    better = _summary([3.0, 2.0, 1.0, 0.5])
    worse = _summary([3.0, 2.5, 2.2, 2.0])
    report = compare_runs(better, worse, label_a="A", label_b="B")
    assert report.winner == "a"
    assert "Победитель: A" in report.verdict
    assert report.converge_a is not None  # reaches the shared target
    assert report.converge_b is None      # worse run never gets there

    flipped = compare_runs(worse, better, label_a="X", label_b="Y")
    assert flipped.winner == "b"

    identical = compare_runs(better, _summary([3.0, 2.0, 1.0, 0.5]))
    assert identical.winner == "tie"

    empty = compare_runs(MetricsSummary(), MetricsSummary())
    assert empty.verdict == "Недостаточно метрик для сравнения."


def test_overlay_series_layout():
    series = overlay_series("loss", _summary([2.0, 1.0]), _summary([3.0, 2.0, 1.0]),
                            label_a="A", label_b="B")
    assert series == {"A": [2.0, 1.0], "B": [3.0, 2.0, 1.0]}


def test_suggest_fixes_scenarios():
    # Rising loss → lower lr with high confidence.
    rising = suggest_fixes(_summary([1.0, 1.1, 1.2, 1.3]), {"lr": 0.05})
    params = {s.param: s for s in rising}
    assert params["lr"].value < 0.05
    assert params["lr"].confidence == "high"

    # Spike → lr down + grad_clip.
    spiked = suggest_fixes(_summary([1.0, 0.8, 5.0]), {"lr": 0.1})
    names = {s.param for s in spiked}
    assert {"lr", "grad_clip"} <= names

    # Plateau → early stop suggested when not set.
    plateau = suggest_fixes(_summary([1.0, 1.0, 1.0, 1.0, 1.0]), {"lr": 0.05})
    assert any(s.param == "early_stop_patience" for s in plateau)

    # Healthy improving run → keep or tiny bump.
    healthy = suggest_fixes(_summary([3.0, 2.0, 1.0, 0.5]), {"lr": 0.05})
    assert all(s.param == "lr" for s in healthy)

    # apply_suggestions merges into a patch.
    patch = apply_suggestions({"lr": 0.05}, rising)
    assert patch["lr"] < 0.05


def test_suggest_fixes_overfitting_signal():
    summary = _summary([3.0, 2.0, 1.5, 1.2, 1.0],
                       val_losses=[3.1, 2.2, 1.8, 2.5, 3.0])
    suggestions = suggest_fixes(summary, {"lr": 0.05})
    assert any(s.param == "early_stop_patience" for s in suggestions)
