"""Hyperparameter suggestions from training metrics (watchdog-driven).

The agent reads the suggestions and applies chosen ones through
``set_training_control``; the UI offers the same via a single button.
"""
from __future__ import annotations

from dataclasses import dataclass

from .metrics import MetricsSummary
from .watchdog import detect_issues


@dataclass
class Suggestion:
    param: str          # key in control.json
    value: float | int | bool | str
    reason: str
    confidence: str     # "high" | "medium" | "low"

    def line(self) -> str:
        mark = {"high": "★", "medium": "☆", "low": "·"}.get(self.confidence, "·")
        return f"{mark} {self.param} = {self.value} — {self.reason}"


def _current(control: dict, key: str, default: float) -> float:
    try:
        return float(control.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def suggest_fixes(summary: MetricsSummary, control: dict | None = None) -> list[Suggestion]:
    """Propose control.json changes from the current training dynamics."""
    control = dict(control or {})
    suggestions: list[Suggestion] = []
    losses = summary.series("loss")
    lr = _current(control, "lr", 0.05)
    codes = {issue.code for issue in detect_issues(summary, running=True)}

    if "nan" in codes:
        suggestions.append(Suggestion(
            "lr", max(1e-6, round(lr * 0.1, 6)),
            "NaN/Inf в метриках: резко снизьте lr", "high"))
        suggestions.append(Suggestion(
            "grad_clip", 1.0,
            "Ограничение градиентов стабилизирует численно неустойчивый шаг",
            "high"))
        return suggestions

    if "spike" in codes:
        suggestions.append(Suggestion(
            "lr", round(lr * 0.5, 6),
            "Всплеск loss: умеренно снизьте lr", "high"))
        suggestions.append(Suggestion(
            "grad_clip", 1.0, "Подстраховка от новых всплесков", "medium"))

    if "rising" in codes:
        suggestions.append(Suggestion(
            "lr", round(lr * 0.3, 6),
            "Loss растёт несколько эпох: lr слишком высок", "high"))

    if "plateau" in codes:
        suggestions.append(Suggestion(
            "lr", round(lr * 0.5, 6),
            "Плато: попробуйте меньший шаг", "medium"))
        if int(control.get("early_stop_patience", 0) or 0) == 0:
            suggestions.append(Suggestion(
                "early_stop_patience", 3,
                "Остановка при отсутствии улучшений сэкономит время", "medium"))

    # Overfitting signal: val_loss series pulls away from train_loss.
    val = summary.series("val_loss")
    train = summary.series("loss") or summary.series("train_loss")
    if len(val) >= 3 and len(train) >= 3:
        if val[-1] > min(val) * 1.05 and train[-1] < train[0]:
            if int(control.get("early_stop_patience", 0) or 0) == 0:
                suggestions.append(Suggestion(
                    "early_stop_patience", 2,
                    "Признаки переобучения: ограничьте хвост обучения", "high"))

    if not suggestions and losses and losses[-1] == losses[-1]:
        improvements = [abs(losses[i] - losses[i - 1]) for i in range(1, len(losses))]
        if improvements and improvements[-1] < 1e-3:
            suggestions.append(Suggestion(
                "lr", round(lr * 1.1, 6),
                "Обучение стабильно и почти не двигается: слегка увеличьте lr",
                "low"))
        else:
            suggestions.append(Suggestion(
                "lr", round(lr, 6), "Параметры в норме — оставьте как есть",
                "low"))
    return suggestions


def apply_suggestions(control: dict, suggestions: list[Suggestion]) -> dict:
    """Merge chosen suggestions into a control patch (no I/O)."""
    patch = dict(control)
    for suggestion in suggestions:
        patch[suggestion.param] = suggestion.value
    return patch
