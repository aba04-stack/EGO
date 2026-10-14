"""Benchmark history (stage 45): trends per model over time.

Every benchmark (speed probes and live scenario benches) lands in one
store; this module turns the raw list into a history table with
deltas against the previous run of the *same model and kind*, a
latest-per-model comparison, and CSV export — so «did the new
checkpoint / provider get better?» is a lookup, not a memory test.
"""
from __future__ import annotations

import csv
import io
import time

from .bench import BenchResult

KIND_LABELS = {"speed": "скорость", "live": "сценарии"}


def _score(result: BenchResult) -> float:
    """Comparable score: live = pass share, speed = tokens/sec."""
    if result.kind == "live":
        return (result.passed / result.total) if result.total else 0.0
    return result.tokens_per_sec


def _score_text(result: BenchResult) -> str:
    if result.kind == "live":
        return f"{result.passed}/{result.total}"
    if result.tokens_per_sec:
        return f"{result.tokens_per_sec:.0f} tok/s"
    return f"{result.duration_ms} мс"


def _delta_text(current: float, previous: float | None) -> str:
    if previous is None or previous == 0:
        return "—"
    change = (current - previous) / previous * 100.0
    if abs(change) < 0.5:
        return "≈0%"
    return f"{'▲' if change > 0 else '▼'} {abs(change):.0f}%"


def with_deltas(results: list[BenchResult]) -> list[tuple[BenchResult, str]]:
    """Each result paired with its delta vs previous same model+kind."""
    ordered = sorted(results, key=lambda r: r.created_at)
    previous: dict[tuple[str, str], float] = {}
    deltas: dict[str, str] = {}
    for result in ordered:
        key = (result.model, result.kind)
        deltas[result.id] = _delta_text(_score(result), previous.get(key))
        if result.ok():
            previous[key] = _score(result)
    newest_first = sorted(results, key=lambda r: -r.created_at)
    return [(r, deltas.get(r.id, "—")) for r in newest_first]


def history_table(results: list[BenchResult], limit: int = 20) -> str:
    """Aligned history table, newest first, with per-model deltas."""
    if not results:
        return "История бенчмарков пуста — запустите «Бенчмарк модели»."
    header = (f"{'Дата':<17}{'Модель':<26}{'Тип':<10}"
              f"{'Результат':>12}{'Δ к пред.':>11}")
    rows = [header, "-" * len(header)]
    for result, delta in with_deltas(results)[:limit]:
        stamp = time.strftime("%Y-%m-%d %H:%M",
                              time.localtime(result.created_at))
        rows.append(
            f"{stamp:<17}{result.model[:25]:<26}"
            f"{KIND_LABELS.get(result.kind, result.kind):<10}"
            f"{_score_text(result):>12}{delta:>11}")
    return "\n".join(rows)


def latest_per_model(results: list[BenchResult]) -> dict[str, BenchResult]:
    latest: dict[str, BenchResult] = {}
    for result in sorted(results, key=lambda r: -r.created_at):
        latest.setdefault(f"{result.model}|{result.kind}", result)
    return latest


def compare_latest(results: list[BenchResult]) -> list[str]:
    """One line per model+kind with its freshest score, best first."""
    latest = latest_per_model(results)
    if not latest:
        return ["Нет замеров для сравнения моделей."]
    rows = []
    for result in sorted(latest.values(), key=lambda r: -_score(r)):
        rows.append(f"{result.model} ({KIND_LABELS.get(result.kind, result.kind)}): "
                    f"{_score_text(result)} · "
                    f"{time.strftime('%Y-%m-%d', time.localtime(result.created_at))}")
    return rows


def to_csv(results: list[BenchResult]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "model", "kind", "passed", "total",
                     "duration_ms", "tokens_per_sec", "score", "delta"])
    for result, delta in with_deltas(results):
        writer.writerow([
            time.strftime("%Y-%m-%d %H:%M:%S",
                          time.localtime(result.created_at)),
            result.model, result.kind, result.passed, result.total,
            result.duration_ms, result.tokens_per_sec,
            f"{_score(result):.3f}", delta])
    return buffer.getvalue()
