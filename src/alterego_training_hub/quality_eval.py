"""Reproducible quality evaluation on FIXED cases (not just loss).

Loss going down on a tiny dataset proves optimization works, not that the
model got better.  This module scores generations on a held-out fixed case
set (same prompts before/after training), checks metric series for
NaN/Inf, and renders an honest before/after verdict.  The responder is
injected, so any backend (local server, HF model, agent) can be scored.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FixedCase:
    prompt: str
    expected_any: tuple[str, ...] = ()  # any substring (case-insensitive) = pass
    tag: str = ""


@dataclass
class QualityReport:
    total: int = 0
    passed: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def render(self) -> str:
        lines = [f"Фиксированные задания: {self.passed}/{self.total} "
                 f"({self.rate:.0%})"]
        lines.extend(self.details)
        return "\n".join(lines)


def run_cases(cases, respond) -> QualityReport:
    """Score ``respond(prompt) -> str`` on fixed cases; never raises per-case."""
    report = QualityReport()
    for case in cases or []:
        report.total += 1
        try:
            answer = str(respond(case.prompt) or "")
        except Exception as exc:
            report.details.append(
                f"✗ [{case.tag or case.prompt[:24]}] ошибка генерации: {exc}")
            continue
        if not answer.strip():
            report.details.append(
                f"✗ [{case.tag or case.prompt[:24]}] пустой ответ")
            continue
        if case.expected_any and not any(
                needle.lower() in answer.lower()
                for needle in case.expected_any):
            report.details.append(
                f"✗ [{case.tag or case.prompt[:24]}] нет ожидаемого "
                f"{case.expected_any} в ответе: {answer[:80]!r}")
            continue
        report.passed += 1
        report.details.append(f"✓ [{case.tag or case.prompt[:24]}]")
    return report


def scan_metric_health(values) -> list[str]:
    """NaN/Inf и взрывы в ряде метрик — обучение сломано, даже если «идёт»."""
    problems: list[str] = []
    seq = [float(v) for v in (values or [])]
    for i, value in enumerate(seq):
        if math.isnan(value):
            problems.append(f"шаг {i + 1}: NaN — обучение развалилось "
                            "(lr слишком велик или данные битые)")
            break
        if math.isinf(value):
            problems.append(f"шаг {i + 1}: Inf — численная нестабильность")
            break
    if len(seq) >= 3 and seq[-1] > seq[0] * 3 and seq[-1] > 5:
        problems.append(f"loss вырос {seq[0]:.3f} → {seq[-1]:.3f} — "
                        "признак расходимости, а не обучения")
    return problems


def compare_quality(before: QualityReport, after: QualityReport) -> str:
    """Честный вердикт до/после на ОДНИХ и тех же фиксированных заданиях."""
    if before.total == 0 or after.total == 0:
        return "Недостаточно данных: прогоните фиксированные задания до и после."
    delta = after.rate - before.rate
    if delta > 0.05:
        verdict = "качество ВЫРОСЛО"
    elif delta < -0.05:
        verdict = "качество УПАЛО (регрессия — проверьте данные и lr)"
    else:
        verdict = "качество не изменилось заметно"
    return (f"До: {before.passed}/{before.total} ({before.rate:.0%}) · "
            f"После: {after.passed}/{after.total} ({after.rate:.0%}) · "
            f"{verdict}. Оценка по фиксированным заданиям, не по loss.")
