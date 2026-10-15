"""Этап 33: параллельные readonly-вызовы, порядок и безопасность мутаций."""
import threading
import time

from alterego_training_hub.agent import MentorAgent
from alterego_training_hub.mentor import MentorReply, ToolCall
from alterego_training_hub.tools import WorkspaceTools


def _reply(text="", calls=()):
    return MentorReply(text=text, model="fake",
                       usage={"prompt_tokens": 1, "completion_tokens": 1},
                       tool_calls=tuple(calls))


class _Scripted:
    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)

    def respond(self, messages, *, tools=None, max_tokens=0, temperature=0.0):
        return self.replies.pop(0) if self.replies else _reply("конец")


def test_readonly_calls_run_concurrently(tmp_path):
    """Two slow reads must overlap: a barrier(2) deadlocks if sequential."""
    (tmp_path / "a.txt").write_text("A\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B\n", encoding="utf-8")
    barrier = threading.Barrier(2)

    def slow_read(args):
        barrier.wait(timeout=5)  # passes only when both run at once
        time.sleep(0.05)
        return {"ok": True, "text": args.get("path", "")}

    calls = [ToolCall(id="1", name="slow_read", arguments={"path": "a.txt"}),
             ToolCall(id="2", name="slow_read", arguments={"path": "b.txt"})]
    agent = MentorAgent(_Scripted([_reply(calls=calls), _reply("итог")]),
                        WorkspaceTools(tmp_path), autonomy="agent",
                        extra_tools={"slow_read": slow_read})
    events = {}
    final = agent.run_turn(
        [{"role": "user", "content": "прочитай оба"}],
        on_event=lambda k, p: events.setdefault(k, []).append(p))
    assert final.text == "итог"
    assert events.get("parallel_batch"), "readonly-вызовы не ушли в параллель"
    assert events["parallel_batch"][0]["count"] == 2
    results = [p for p in events.get("tool_result", [])]
    assert all(p.get("ok") for p in results)


def test_result_order_preserved(tmp_path):
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name + "\n", encoding="utf-8")

    def read(args):
        return {"ok": True, "text": args["path"]}

    calls = [ToolCall(id=str(i), name="read_file",
                      arguments={"path": n})
             for i, n in enumerate(("c.txt", "a.txt", "b.txt"))]
    transcript: list[dict] = []
    agent = MentorAgent(_Scripted([_reply(calls=calls), _reply("ок")]),
                        WorkspaceTools(tmp_path), autonomy="agent")
    agent.run_turn([{"role": "user", "content": "читай"}],
                   transcript=transcript)
    tool_msgs = [m for m in transcript if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["0", "1", "2"]
    assert "c.txt" in tool_msgs[0]["content"]


def test_mutations_stay_sequential_and_confirmed(tmp_path):
    order: list[str] = []

    def writer(args):
        order.append("start")
        time.sleep(0.05)
        order.append("end")
        return {"ok": True}

    calls = [ToolCall(id="1", name="do_write", arguments={}),
             ToolCall(id="2", name="do_write", arguments={})]
    confirms: list[str] = []
    agent = MentorAgent(
        _Scripted([_reply(calls=calls), _reply("ок")]),
        WorkspaceTools(tmp_path), autonomy="assist",
        extra_tools={"do_write": writer},
        extra_mutations=frozenset({"do_write"}))
    events = {}
    agent.run_turn(
        [{"role": "user", "content": "пиши"}],
        confirm=lambda name, args, desc: confirms.append(name) or True,
        on_event=lambda k, p: events.setdefault(k, []).append(p))
    assert order == ["start", "end", "start", "end"]  # не перемежаются
    assert confirms == ["do_write", "do_write"]
    assert not events.get("parallel_batch")


def test_parallel_safe_classification(tmp_path):
    agent = MentorAgent(_Scripted([]), WorkspaceTools(tmp_path),
                        autonomy="agent")
    assert agent._parallel_safe(ToolCall(id="1", name="read_file",
                                         arguments={}))
    assert agent._parallel_safe(ToolCall(id="2", name="search_files",
                                         arguments={}))
    assert not agent._parallel_safe(ToolCall(id="3", name="write_file",
                                             arguments={}))
    assert not agent._parallel_safe(ToolCall(id="4", name="run_command",
                                             arguments={}))
