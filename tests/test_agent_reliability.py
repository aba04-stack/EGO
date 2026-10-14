"""Этап 30: надёжность агента — классификация ошибок, retry, loop-guard, бенчмарк."""
import pytest

from alterego_training_hub.agent import (
    LoopGuard,
    MentorAgent,
    TurnStats,
    classify_error,
    is_transient,
    respond_with_retry,
)
from alterego_training_hub.agent_bench import run_benchmark
from alterego_training_hub.mentor import MentorError, MentorReply, ToolCall
from alterego_training_hub.tools import WorkspaceTools


def test_classify_error_categories():
    assert classify_error("Request timeout 503") == "transient"
    assert classify_error(TimeoutError()) == "transient"
    assert classify_error("403 permission denied") == "permission"
    assert classify_error("File not found") == "not_found"
    assert classify_error("Invalid argument: required") == "validation"
    assert classify_error("something else") == "fatal"
    assert is_transient("429 rate limit")


class _FlakyMentor:
    model = "flaky"

    def __init__(self, failures: int, error: str = "503 temporarily unavailable"):
        self.failures, self.error, self.calls = failures, error, 0

    def respond(self, messages, *, tools=None, max_tokens=0, temperature=0.0):
        self.calls += 1
        if self.calls <= self.failures:
            raise MentorError(self.error)
        return MentorReply(text="ok", model=self.model, usage={})


def test_retry_recovers_from_transient():
    mentor = _FlakyMentor(2)
    retries = []
    reply = respond_with_retry(mentor, [{"role": "user", "content": "x"}],
                               sleep=lambda _s: None,
                               on_retry=lambda a, c: retries.append((a, c)))
    assert reply.text == "ok" and mentor.calls == 3 and len(retries) == 2


def test_retry_does_not_retry_fatal():
    mentor = _FlakyMentor(5, error="401 unauthorized")
    with pytest.raises(MentorError):
        respond_with_retry(mentor, [{"role": "user", "content": "x"}],
                           sleep=lambda _s: None)
    assert mentor.calls == 1


def test_loop_guard_signatures():
    guard = LoopGuard(limit=3)
    assert not guard.check("read_file", {"path": "a"}, False)
    assert not guard.check("read_file", {"path": "a"}, False)
    assert guard.check("read_file", {"path": "a"}, False)
    assert "read_file" in guard.tripped
    other = LoopGuard(limit=3)
    assert not other.check("read_file", {"path": "a"}, True)
    assert not other.check("read_file", {"path": "b"}, True)  # другие аргументы
    assert other.repeats() == 1


def _reply(text="", calls=()):
    return MentorReply(text=text, model="fake",
                       usage={"prompt_tokens": 3, "completion_tokens": 2},
                       tool_calls=tuple(calls))


class _Scripted:
    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)

    def respond(self, messages, *, tools=None, max_tokens=0, temperature=0.0):
        return self.replies.pop(0) if self.replies else _reply("конец")


def test_run_turn_stats_and_loop_stop(tmp_path):
    (tmp_path / "a.txt").write_text("hi\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    failing = _reply(calls=[ToolCall(id="1", name="read_file",
                                     arguments={"path": "nope.txt"})])
    agent = MentorAgent(_Scripted([failing, failing, failing, failing]),
                        tools, autonomy="agent")
    events = {}
    final = agent.run_turn(
        [{"role": "user", "content": "читай"}],
        on_event=lambda k, p: events.setdefault(k, []).append(p))
    assert events.get("loop_detected")
    assert "зацикливания" in final.text
    stats = events["finished"][-1]["stats"]
    assert stats["loop_tripped"] and stats["tool_errors"] >= 3
    assert stats["prompt_tokens"] > 0


def test_run_turn_retry_event_and_stats(tmp_path):
    tools = WorkspaceTools(tmp_path)
    agent = MentorAgent(_FlakyMentor(1), tools, autonomy="agent")
    events = {}
    final = agent.run_turn(
        [{"role": "user", "content": "привет"}],
        on_event=lambda k, p: events.setdefault(k, []).append(p))
    assert final.text == "ok"
    assert events.get("retry")
    assert events["finished"][-1]["stats"]["retries"] == 1


def test_turn_stats_render():
    stats = TurnStats(steps=2, tool_calls=3, tool_errors=1)
    assert "Шагов: 2" in stats.render()
    assert stats.as_dict()["tool_errors"] == 1


def test_agent_benchmark_all_pass(tmp_path):
    report = run_benchmark(workspace_factory=lambda name: tmp_path / name)
    assert report.ok, report.render()
    assert report.total == 5
    assert "5/5" in report.render()
