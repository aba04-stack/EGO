"""Internal agent benchmark (этап 30): scripted scenarios, measurable score.

SWE-bench-style idea, offline and deterministic: a scripted mentor drives
the *real* :class:`~alterego_training_hub.agent.MentorAgent` loop and the
*real* :class:`~alterego_training_hub.tools.WorkspaceTools` on a temporary
workspace.  It verifies the harness (loop, tools, confirmations, readonly
guarantees, loop-guard), not a specific LLM — so it can run in CI on every
change and prove the agent machinery did not regress.

Scenarios: fix a file, find-and-fix a bug via search, verify-after-edit,
readonly must not mutate, loop-guard stops repetition.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .agent import MentorAgent
from .mentor import ApiMentor, MentorReply, ToolCall
from .tools import WorkspaceTools


class ScriptedMentor:
    """Deterministic mentor replaying a queue of replies."""

    model = "scripted-bench"

    def __init__(self, script: list[MentorReply]):
        self._script = list(script)
        self.calls = 0

    def respond(self, messages, *, tools=None, max_tokens=700,
                temperature=0.2) -> MentorReply:
        self.calls += 1
        if self._script:
            return self._script.pop(0)
        return MentorReply(text="Готово.", model=self.model, usage={})


def _reply(text: str = "", calls: list[tuple[str, dict]] | None = None,
           usage: dict | None = None) -> MentorReply:
    tool_calls = tuple(
        ToolCall(id=f"bench-{i}", name=name, arguments=dict(args))
        for i, (name, args) in enumerate(calls or []))
    return MentorReply(text=text, model="scripted-bench",
                       usage=usage or {"prompt_tokens": 10,
                                       "completion_tokens": 5},
                       tool_calls=tool_calls)


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str = ""
    steps: int = 0
    tool_errors: int = 0
    seconds: float = 0.0


@dataclass
class BenchReport:
    results: list[ScenarioResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total

    def render(self) -> str:
        rows = [f"🧪 Бенчмарк агента: {self.passed}/{self.total} сценариев"]
        for r in self.results:
            mark = "✓" if r.passed else "✗"
            rows.append(f"{mark} {r.name} — {r.detail} "
                        f"(шагов: {r.steps}, ошибок: {r.tool_errors}, "
                        f"{r.seconds:.2f} c)")
        return "\n".join(rows)


def _run(root: Path, script: list[MentorReply], *, readonly: bool = False,
         max_steps: int = 8) -> tuple[MentorReply, dict, WorkspaceTools]:
    events: dict[str, list] = {}
    mentor = ScriptedMentor(script)
    tools = WorkspaceTools(root, backup_dir=root / ".backups")
    agent = MentorAgent(cast(ApiMentor, mentor), tools,
                        autonomy="agent", max_steps=max_steps)
    final = agent.run_turn(
        [{"role": "user", "content": "выполни задачу"}],
        confirm=lambda *_a: True,
        on_event=lambda kind, payload: events.setdefault(kind, []).append(payload),
        readonly=readonly)
    return final, events, tools


def run_benchmark(workspace_factory: Callable[[str], Path] | None = None,
                  ) -> BenchReport:
    """Run all scenarios. ``workspace_factory(name)`` must return a fresh dir."""
    import tempfile

    def default_factory(_name: str) -> Path:
        return Path(tempfile.mkdtemp(prefix="agent-bench-"))

    factory = workspace_factory or default_factory
    report = BenchReport()

    def scenario(name: str, setup: Callable[[Path], Any],
                 script: list[MentorReply],
                 check: Callable[[Path, MentorReply, dict], tuple[bool, str]],
                 *, readonly: bool = False, max_steps: int = 8) -> None:
        started = time.time()
        root = factory(name)
        root.mkdir(parents=True, exist_ok=True)
        setup(root)
        try:
            final, events, _tools = _run(root, script, readonly=readonly,
                                         max_steps=max_steps)
            passed, detail = check(root, final, events)
            finished = events.get("finished", [{}])
            stats = finished[-1].get("stats", {}) if finished else {}
            report.results.append(ScenarioResult(
                name=name, passed=bool(passed), detail=detail,
                steps=int(stats.get("steps", 0) or 0),
                tool_errors=int(stats.get("tool_errors", 0) or 0),
                seconds=round(time.time() - started, 2)))
        except Exception as exc:
            report.results.append(ScenarioResult(
                name=name, passed=False,
                detail=f"исключение: {type(exc).__name__}: {exc}",
                seconds=round(time.time() - started, 2)))

    # 1. Fix a file with replace_in_file, then verify by reading it back.
    scenario(
        "починка файла",
        lambda root: (root / "calc.py").write_text(
            "def add(a, b):\n    return a - b\n", encoding="utf-8"),
        [_reply(calls=[("replace_in_file", {"path": "calc.py",
                                            "find": "a - b",
                                            "replace": "a + b"})]),
         _reply(calls=[("read_file", {"path": "calc.py"})]),
         _reply(text="Исправлено и проверено.")],
        lambda root, final, events: (
            "a + b" in (root / "calc.py").read_text(encoding="utf-8"),
            "файл исправлен" if "a + b" in (root / "calc.py").read_text(
                encoding="utf-8") else "файл не исправлен"))

    # 2. Find a bug via search, then fix it.
    scenario(
        "поиск и исправление бага",
        lambda root: (root / "app.py").write_text(
            "TOKEN = 'hardcoded-secret'\n", encoding="utf-8"),
        [_reply(calls=[("search_files", {"pattern": "hardcoded"})]),
         _reply(calls=[("replace_in_file", {"path": "app.py",
                                            "find": "'hardcoded-secret'",
                                            "replace": "os.environ['TOKEN']"})]),
         _reply(text="Секрет вынесен в окружение.")],
        lambda root, final, events: (
            "hardcoded-secret" not in (root / "app.py").read_text(
                encoding="utf-8"),
            "секрет удалён из кода"))

    # 3. Create a new file via write_file.
    scenario(
        "создание файла",
        lambda root: None,
        [_reply(calls=[("write_file", {"path": "notes.md",
                                       "content": "# Заметки\n"})]),
         _reply(text="Файл создан.")],
        lambda root, final, events: (
            (root / "notes.md").is_file(), "файл создан"))

    # 4. Readonly mode must reject mutations.
    def _readonly_check(root, final, events):
        content = (root / "data.txt").read_text(encoding="utf-8")
        rejected = any(
            not payload.get("ok", True)
            for payload in events.get("tool_result", []))
        return (content == "original\n" and rejected,
                "мутация отклонена" if content == "original\n" else "ФАЙЛ ИЗМЕНЁН")

    scenario(
        "readonly не мутирует",
        lambda root: (root / "data.txt").write_text("original\n",
                                                    encoding="utf-8"),
        [_reply(calls=[("write_file", {"path": "data.txt",
                                       "content": "hacked\n"})]),
         _reply(text="Не удалось изменить.")],
        _readonly_check, readonly=True)

    # 5. Loop-guard stops a mentor repeating the same failing call.
    def _loop_check(root, final, events):
        stopped = bool(events.get("loop_detected"))
        honest = "зацикливания" in (final.text or "")
        return (stopped and honest,
                "цикл остановлен" if stopped else "цикл НЕ остановлен")

    failing = _reply(calls=[("read_file", {"path": "missing.txt"})])
    scenario(
        "loop-guard от зацикливания",
        lambda root: None,
        [failing, failing, failing, failing, failing],
        _loop_check)

    return report
