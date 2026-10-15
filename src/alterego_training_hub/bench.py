"""Benchmarks: measure model commands, store results, compare and rank.

A benchmark runs a user-provided command (model CLI, inference script) a few
times, measures wall time and parses an optional ``tokens=N`` marker from
output to compute tokens/sec. Results persist to benchmarks.json.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

TOKENS_RE = re.compile(r"tokens=(\d+)")
DEFAULT_ITERATIONS = 3
DEFAULT_WARMUP = 1


class BenchError(RuntimeError):
    """Benchmark input error safe to display."""


@dataclass
class BenchResult:
    model: str
    command: str
    iterations: int = 0
    duration_ms: int = 0            # mean wall time per run
    tokens_per_sec: float = 0.0     # parsed from tokens=N output
    output_chars: int = 0
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    error: str = ""
    kind: str = "speed"  # speed | live
    passed: int = 0      # live benches: scenarios passed
    total: int = 0       # live benches: scenarios total

    def ok(self) -> bool:
        return not self.error

    def line(self) -> str:
        if self.error:
            return f"{self.model}: ошибка — {self.error}"
        speed = f"{self.tokens_per_sec:.1f} tok/s" if self.tokens_per_sec else "—"
        return (f"{self.model}: {self.duration_ms} мс/запуск, {speed}, "
                f"вывод {self.output_chars} симв.")


def parse_tokens(text: str) -> int:
    matches = TOKENS_RE.findall(str(text or ""))
    return int(matches[-1]) if matches else 0


def run_benchmark(model: str, command: str, *, iterations: int = DEFAULT_ITERATIONS,
                  warmup: int = DEFAULT_WARMUP, timeout_seconds: float = 300.0,
                  cwd: str | None = None, runner=None) -> BenchResult:
    """Run the command several times and aggregate timings."""
    iterations = max(1, min(int(iterations), 20))
    warmup = max(0, min(int(warmup), 5))
    if not str(command).strip():
        raise BenchError("Команда для бенчмарка не должна быть пустой.")
    import shlex

    try:
        if os.name == "nt":
            # Keep Windows executable paths intact; shlex POSIX mode treats backslashes as escapes.
            argv = shlex.split(command, posix=False)
            argv = [
                token[1:-1]
                if len(token) >= 2 and token[0] == token[-1]
                and token[0] in {"'", '"'}
                else token
                for token in argv
            ]
        else:
            argv = shlex.split(command)
    except ValueError as exc:
        raise BenchError(f"Не удалось разобрать команду: {exc}") from None
    durations: list[float] = []
    tokens = 0
    output_chars = 0
    for index in range(warmup + iterations):
        started = time.monotonic()
        try:
            if runner is not None:
                completed = runner(argv)
                returncode = getattr(completed, "returncode", 0)
                output = str(getattr(completed, "stdout", "") or "")
            else:
                completed = subprocess.run(argv, capture_output=True, text=True,
                                           timeout=max(5.0, float(timeout_seconds)),
                                           cwd=cwd)
                returncode = completed.returncode
                output = completed.stdout or ""
        except FileNotFoundError:
            return BenchResult(model=model, command=command,
                               error=f"Команда не найдена: {argv[0]}")
        except subprocess.TimeoutExpired:
            return BenchResult(model=model, command=command,
                               error="Превышен таймаут запуска.")
        elapsed = (time.monotonic() - started) * 1000.0
        if returncode != 0:
            return BenchResult(model=model, command=command,
                               error=f"Код возврата {returncode}.")
        if index >= warmup:  # warm-up runs are not measured
            durations.append(elapsed)
            tokens = max(tokens, parse_tokens(output))
            output_chars = max(output_chars, len(output))
    mean_raw = statistics.mean(durations) if durations else 0.0
    # Extremely short no-op commands can measure as 0 on coarse clocks.
    # Use a 1 ms lower bound instead of reporting zero throughput.
    safe_mean_ms = max(mean_raw, 1.0) if durations else 0.0
    mean_ms = max(1, round(safe_mean_ms)) if durations else 0
    tokens_per_sec = (tokens / (safe_mean_ms / 1000.0)) if tokens and safe_mean_ms > 0 \
        else 0.0
    return BenchResult(model=model, command=command, iterations=iterations,
                       duration_ms=mean_ms,
                       tokens_per_sec=round(tokens_per_sec, 2),
                       output_chars=output_chars)


class BenchStore:
    """CRUD over benchmarks.json inside the shared library folder."""

    def __init__(self, library_dir: Path):
        self.library_dir = Path(library_dir)
        self.path = self.library_dir / "benchmarks.json"

    def _load(self) -> list[BenchResult]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out: list[BenchResult] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                out.append(BenchResult(**{
                    key: value for key, value in item.items()
                    if key in BenchResult.__dataclass_fields__}))
            except TypeError:
                continue
        return out

    def _save(self, results: list[BenchResult]) -> Path:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(result) for result in results],
                       ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def add(self, result: BenchResult) -> BenchResult:
        results = self._load()
        results.insert(0, result)
        self._save(results[:50])
        return result

    def list(self, limit: int = 20) -> list[BenchResult]:
        return self._load()[:max(1, int(limit))]


def rank_benchmarks(results: list[BenchResult]) -> list[str]:
    """Russian ranking: fastest mean latency first, tokens/sec second."""
    good = [result for result in results if result.ok()]
    if not good:
        return ["Нет успешных замеров для сравнения."]
    lines = []
    by_speed = sorted(good, key=lambda r: r.duration_ms)
    lines.append("По скорости (мс/запуск): " + " | ".join(
        f"{index + 1}. {r.model} — {r.duration_ms} мс"
        for index, r in enumerate(by_speed[:5])))
    with_tokens = [r for r in good if r.tokens_per_sec > 0]
    if with_tokens:
        by_tokens = sorted(with_tokens, key=lambda r: -r.tokens_per_sec)
        lines.append("По токенам (tok/s): " + " | ".join(
            f"{index + 1}. {r.model} — {r.tokens_per_sec:.1f}"
            for index, r in enumerate(by_tokens[:5])))
    lines.append(f"Лучший результат: {by_speed[0].model}")
    return lines


def format_bench_table(results: list[BenchResult]) -> str:
    """Aligned text table for the UI/agent reports."""
    header = f"{'Модель':<24}{'мс/запуск':>10}{'tok/s':>10}{'Замеры':>8}"
    rows = [header, "-" * len(header)]
    for result in results[:15]:
        rows.append(
            f"{result.model[:24]:<24}"
            f"{result.duration_ms if result.ok() else '—':>10}"
            f"{(f'{result.tokens_per_sec:.1f}' if result.tokens_per_sec else '—'):>10}"
            f"{result.iterations:>8}")
    return "\n".join(rows)
