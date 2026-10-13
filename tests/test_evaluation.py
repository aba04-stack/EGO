"""Tests for the evaluation pipeline (perplexity, eval points, overfitting)."""
from __future__ import annotations

import math

from alterego_training_hub.evaluation import (
    build_eval_report,
    parse_eval_points,
    perplexity,
)


def test_perplexity_clamped_and_nan():
    assert math.isclose(perplexity(0.0), 1.0)
    assert math.isclose(perplexity(math.log(10)), 10.0)
    assert perplexity(100.0) == math.exp(20.0)  # clamped, no overflow
    assert perplexity(float("nan")) != perplexity(float("nan"))


def test_parse_eval_points_same_line_style():
    log = "\n".join([
        "config: lr=0.05 epochs=3 n=256",
        "epoch 1/3 loss=4.0 acc=0.5 val_loss=4.2 val_acc=0.48 perplexity=66.6 lr=0.05",
        "epoch 2/3 loss=2.0 acc=0.7 val_loss=2.1 val_acc=0.69 perplexity=8.1 lr=0.05",
        "epoch 3/3 loss=1.0 acc=0.8 val_loss=1.5 val_acc=0.72 perplexity=4.4 lr=0.05",
    ])
    points = parse_eval_points(log)
    assert [point.epoch for point in points] == [1, 2, 3]
    assert points[0].val_loss == 4.2 and points[0].train_loss == 4.0
    assert points[1].perplexity == 8.1


def test_parse_eval_points_separate_eval_lines():
    log = "\n".join([
        "epoch 1/2 loss=3.0 acc=0.5 lr=0.05",
        "eval: val_loss=3.1 val_acc=0.5 perplexity=22.2",
        "epoch 2/2 loss=1.0 acc=0.8 lr=0.05",
        "eval: val_loss=1.2 val_acc=0.78",
    ])
    points = parse_eval_points(log)
    assert len(points) == 2
    assert points[0].val_loss == 3.1 and points[0].perplexity == 22.2
    assert points[1].val_acc == 0.78
    assert points[1].perplexity == perplexity(1.2)  # computed when absent


def test_build_eval_report_best_and_overfitting():
    healthy = "\n".join(
        f"epoch {e}/5 loss={4 - e:.2f} acc=0.5 val_loss={4.1 - e:.2f} "
        f"val_acc=0.5 lr=0.05" for e in range(1, 6))
    report = build_eval_report(healthy)
    assert report.best_epoch == 5
    assert report.overfitting is False
    assert "здоровым темпом" in report.verdict

    overfit = "\n".join([
        "epoch 1/5 loss=3.0 acc=0.5 val_loss=3.0 val_acc=0.5 lr=0.05",
        "epoch 2/5 loss=2.0 acc=0.6 val_loss=2.5 val_acc=0.55 lr=0.05",
        "epoch 3/5 loss=1.0 acc=0.7 val_loss=2.2 val_acc=0.6 lr=0.05",
        "epoch 4/5 loss=0.5 acc=0.8 val_loss=3.5 val_acc=0.5 lr=0.05",
        "epoch 5/5 loss=0.3 acc=0.85 val_loss=4.0 val_acc=0.45 lr=0.05",
    ])
    report = build_eval_report(overfit)
    assert report.best_epoch == 3
    assert report.overfitting is True
    assert "переобучения" in " ".join(report.lines())
    assert "early_stop_patience" in report.verdict

    empty = build_eval_report("no metrics here")
    assert empty.best_epoch is None
    assert "Нет валидационных метрик" in empty.verdict
