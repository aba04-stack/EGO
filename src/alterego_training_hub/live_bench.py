"""Live model benchmark (этап 34): the real LLM from settings, measured.

Runs a small scripted task set in throwaway workspaces and verifies outcomes
on disk / in the reply — not by vibes.  Each scenario has a hard timeout;
the report carries success, steps, tokens, estimated cost and wall time, so
models can be compared honestly before trusting one with real work.

The mentor is injected (``app.mentor_client()`` in the UI, fakes in tests) —
this module never reads settings or touches the network itself.
"""
from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import MentorAgent
from .agent_bench import BenchReport, ScenarioResult
from .context_view import estimate_cost
from .tools import WorkspaceTools

DEFAULT_TIMEOUT = 120.0  # seconds per scenario


@dataclass
class LiveBenchReport:
    model: str = ""
    results: list[ScenarioResult] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total

    @property
    def cost_usd(self) -> float:
        return estimate_cost(self.prompt_tokens, self.completion_tokens,
                             self.model)

    def render(self) -> str:
        rows = [f"🧪 Бенчмарк модели {self.model or '—'}: "
                f"{self.passed}/{self.total} задач"]
        for r in self.results:
            mark = "✓" if r.passed else "✗"
            rows.append(f"{mark} {r.name} — {r.detail} "
                        f"(шагов: {r.steps}, ошибок: {r.tool_errors}, "
                        f"{r.seconds:.1f} c)")
        rows.append(f"Токены: {self.prompt_tokens}→{self.completion_tokens} · "
                    f"оценка стоимости: ≈${self.cost_usd:.4f} · "
                    f"время: {self.seconds:.1f} c")
        return "\n".join(rows)


def _scenario(name: str, setup: Callable[[Path], None], goal: str,
              check: Callable[[Path, str], tuple[bool, str]]):
    return (name, setup, goal, check)


def default_scenarios():
    """The live task set: fix, create, inspect-and-answer."""
    return [
        _scenario(
            "исправь баг",
            lambda root: (root / "calc.py").write_text(
                "def add(a, b):\n    return a - b  # БАГ: должно быть +\n",
                encoding="utf-8"),
            "В файле calc.py функция add вычитает вместо сложения. "
            "Исправь баг и проверь чтением файла.",
            lambda root, text: (
                "a + b" in (root / "calc.py").read_text(encoding="utf-8"),
                "add исправлена" if "a + b" in (root / "calc.py").read_text(
                    encoding="utf-8") else "файл не исправлен")),
        _scenario(
            "создай файл",
            lambda root: None,
            "Создай файл notes.md с первой строкой «# Заметки проекта».",
            lambda root, text: (
                (root / "notes.md").is_file()
                and (root / "notes.md").read_text(
                    encoding="utf-8").startswith("# Заметки проекта"),
                "notes.md создан")),
        _scenario(
            "ответь по файлу",
            lambda root: (root / "config.txt").write_text(
                "mode=nightly\nretries=3\n", encoding="utf-8"),
            "Прочитай config.txt и ответь, какое значение у ключа mode. "
            "Файлы не изменяй.",
            lambda root, text: (
                "nightly" in (text or ""),
                "значение mode названо" if "nightly" in (text or "")
                else "значение не названо")),
    ]


def run_live_benchmark(mentor: Any, *, timeout: float = DEFAULT_TIMEOUT,
                       scenarios=None, model: str = "",
                       root_factory: Callable[[], Path] | None = None,
                       ) -> LiveBenchReport:
    """Run scenarios against a live mentor; failures are results, not raises."""
    report = LiveBenchReport(model=model or getattr(mentor, "model", "") or "")
    tasks = scenarios if scenarios is not None else default_scenarios()
    started_all = time.time()

    def make_root() -> Path:
        if root_factory is not None:
            return root_factory()
        return Path(tempfile.mkdtemp(prefix="live-bench-"))

    for name, setup, goal, check in tasks:
        started = time.time()
        root = make_root()
        root.mkdir(parents=True, exist_ok=True)
        setup(root)
        events: dict[str, list] = {}

        def work() -> str:
            tools = WorkspaceTools(root, backup_dir=root / ".backups")
            agent = MentorAgent(mentor, tools, autonomy="agent",
                                max_steps=10)
            final = agent.run_turn(
                [{"role": "user", "content": goal}],
                confirm=lambda *_a: True,
                on_event=lambda k, p: events.setdefault(k, []).append(p))
            return final.text or ""

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            text = pool.submit(work).result(timeout=timeout)
            passed, detail = check(root, text)
        except FutureTimeout:
            passed, detail = False, f"таймаут {timeout:.0f} c"
            text = ""
        except Exception as exc:
            passed, detail = False, f"{type(exc).__name__}: {exc}"[:160]
        finally:
            pool.shutdown(wait=False)
        finished = events.get("finished", [{}])
        stats = finished[-1].get("stats", {}) if finished else {}
        report.prompt_tokens += int(stats.get("prompt_tokens", 0) or 0)
        report.completion_tokens += int(
            stats.get("completion_tokens", 0) or 0)
        report.results.append(ScenarioResult(
            name=name, passed=bool(passed), detail=detail,
            steps=int(stats.get("steps", 0) or 0),
            tool_errors=int(stats.get("tool_errors", 0) or 0),
            seconds=round(time.time() - started, 2)))
    report.seconds = round(time.time() - started_all, 2)
    return report


def to_bench_report(report: LiveBenchReport) -> BenchReport:
    """Adapt to the shared offline-report shape when needed."""
    return BenchReport(results=list(report.results))
