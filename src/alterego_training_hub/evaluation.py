"""Evaluation pipeline: perplexity, per-epoch eval points, overfitting verdict.

Parses the ``eval:`` lines produced by template training loops into a report
the UI and the agent can act on. Pure logic — no I/O, no network.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

_EVAL_RE = re.compile(r"eval:\s*(?P<pairs>(?:[a-zA-Z_]+=\S+\s*)+)")
_PAIR_RE = re.compile(r"([a-zA-Z_]+)=(-?\d+(?:\.\d+)?(?:e-?\d+)?|nan|inf|-inf)")
_EPOCH_RE = re.compile(r"epoch\s+(?P<epoch>\d+)/(?P<total>\d+)")


def perplexity(loss: float) -> float:
    """exp(loss) with a safe clamp for huge toy losses."""
    try:
        value = float(loss)
    except (TypeError, ValueError):
        return float("nan")
    if value != value:  # NaN
        return float("nan")
    return math.exp(min(value, 20.0))


@dataclass
class EvalPoint:
    epoch: int
    val_loss: float = float("nan")
    val_acc: float = float("nan")
    train_loss: float = float("nan")
    perplexity: float = float("nan")


@dataclass
class EvalReport:
    points: list[EvalPoint] = field(default_factory=list)
    overfitting: bool = False
    best_epoch: int | None = None
    verdict: str = ""

    @property
    def best_val_loss(self) -> float | None:
        if self.best_epoch is None:
            return None
        for point in self.points:
            if point.epoch == self.best_epoch:
                return point.val_loss
        return None

    def lines(self) -> list[str]:
        out = []
        if self.best_epoch is not None:
            out.append(
                f"Лучшая эпоха: {self.best_epoch} "
                f"(val_loss={self.best_val_loss:.4f}, "
                f"perplexity={perplexity(self.best_val_loss or 0.0):.2f})"
                if self.best_val_loss == self.best_val_loss else
                f"Лучшая эпоха: {self.best_epoch}")
        if self.overfitting:
            out.append("Признаки переобучения: val_loss растёт при снижающемся train_loss.")
        if self.verdict:
            out.append(self.verdict)
        return out


def parse_eval_points(text: str) -> list[EvalPoint]:
    """Pair ``epoch N/M`` lines with the ``eval:`` lines that follow them."""
    points: list[EvalPoint] = []
    current: EvalPoint | None = None
    for line in str(text or "").splitlines():
        epoch_match = _EPOCH_RE.search(line)
        if epoch_match and "eval:" not in line:
            pair = dict(_PAIR_RE.findall(line))
            loss = _num(pair.get("loss"))
            current = EvalPoint(
                epoch=int(epoch_match.group("epoch")),
                train_loss=loss)
            # Val metrics may live on the same epoch line (template style).
            current.val_loss = _num(pair.get("val_loss"))
            current.val_acc = _num(pair.get("val_acc"))
            if "perplexity" in pair:
                current.perplexity = _num(pair.get("perplexity"))
            elif current.val_loss == current.val_loss:
                current.perplexity = perplexity(current.val_loss)
            points.append(current)
            continue
        eval_match = _EVAL_RE.search(line)
        if eval_match and current is not None:
            values = dict(_PAIR_RE.findall(eval_match.group("pairs")))
            current.val_loss = _num(values.get("val_loss"))
            current.val_acc = _num(values.get("val_acc"))
            if "perplexity" in values:
                current.perplexity = _num(values.get("perplexity"))
            elif current.val_loss == current.val_loss:
                current.perplexity = perplexity(current.val_loss)
    return points


def _num(raw: str | None) -> float:
    if raw is None:
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def build_eval_report(text: str) -> EvalReport:
    """Full report from a training log: best epoch, overfitting, verdict."""
    points = [point for point in parse_eval_points(text)
              if point.val_loss == point.val_loss]
    report = EvalReport(points=points)
    if not points:
        report.verdict = "Нет валидационных метрик (eval) в логе."
        return report

    best = min(points, key=lambda point: point.val_loss)
    report.best_epoch = best.epoch

    # Overfitting: val worsens after the best epoch while train improves.
    if len(points) >= 3:
        after = [point for point in points if point.epoch > best.epoch]
        later = after[-1] if after else None
        best_train = best.train_loss if best.train_loss == best.train_loss \
            else float("inf")
        if (later is not None and later.val_loss == later.val_loss
                and later.train_loss == later.train_loss
                and later.val_loss > best.val_loss * 1.05
                and later.train_loss < best_train):
            report.overfitting = True

    final = points[-1]
    if report.overfitting:
        report.verdict = (f"Рекомендация: остановиться на эпохе {best.epoch} "
                          f"или включить раннюю остановку (early_stop_patience).")
    elif final.val_loss == best.val_loss:
        report.verdict = "Валидация улучшается — обучение идёт здоровым темпом."
    else:
        report.verdict = (f"Лучший результат был на эпохе {best.epoch}; "
                          "следите за разрывом train/val.")
    return report
