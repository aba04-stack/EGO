"""Этап 35: отмена хода агента через cancel_event."""
import threading

from alterego_training_hub.agent import MentorAgent
from alterego_training_hub.mentor import MentorReply, ToolCall
from alterego_training_hub.tools import WorkspaceTools


def _reply(text="", calls=()):
    return MentorReply(text=text, model="fake",
                       usage={"prompt_tokens": 1, "completion_tokens": 1},
                       tool_calls=tuple(calls))


class _Scripted:
    model = "fake"

    def __init__(self, replies, on_first=None):
        self.replies = list(replies)
        self.on_first = on_first
        self.calls = 0

    def respond(self, messages, *, tools=None, max_tokens=0, temperature=0.0):
        self.calls += 1
        if self.calls == 1 and self.on_first is not None:
            self.on_first()
        return self.replies.pop(0) if self.replies else _reply("конец")


def test_cancel_before_first_step_executes_nothing(tmp_path):
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    event = threading.Event()
    event.set()  # уже отменено до старта
    executed = []
    agent = MentorAgent(
        _Scripted([_reply(calls=[ToolCall(id="1", name="spy", arguments={})])]),
        WorkspaceTools(tmp_path), autonomy="agent",
        extra_tools={"spy": lambda args: executed.append(1) or {"ok": True}})
    events = {}
    final = agent.run_turn(
        [{"role": "user", "content": "делай"}],
        on_event=lambda k, p: events.setdefault(k, []).append(p),
        cancel_event=event)
    assert "Остановлено пользователем" in final.text
    assert executed == []
    assert events.get("cancelled")


def test_cancel_between_steps_stops_tool_execution(tmp_path):
    event = threading.Event()
    executed = []

    def spy(args):
        executed.append(1)
        return {"ok": True}

    # Ментор на первом ответе просит инструмент и одновременно «пользователь»
    # нажимает Стоп: вызовы этого блока уже не должны выполниться.
    calls = [ToolCall(id="1", name="spy", arguments={})]
    agent = MentorAgent(
        _Scripted([_reply(calls=calls), _reply("не дойдёт")],
                  on_first=event.set),
        WorkspaceTools(tmp_path), autonomy="agent",
        extra_tools={"spy": spy})
    final = agent.run_turn([{"role": "user", "content": "делай"}],
                           cancel_event=event)
    assert "Остановлено пользователем" in final.text
    assert executed == []


def test_no_cancel_runs_to_completion(tmp_path):
    agent = MentorAgent(_Scripted([_reply("привет")]),
                        WorkspaceTools(tmp_path), autonomy="agent")
    final = agent.run_turn([{"role": "user", "content": "привет"}],
                           cancel_event=threading.Event())
    assert final.text == "привет"


def test_run_goal_forwards_cancel(tmp_path):
    event = threading.Event()
    event.set()
    agent = MentorAgent(_Scripted([_reply("стоп")]),
                        WorkspaceTools(tmp_path), autonomy="agent")
    final = agent.run_goal("цель", cancel_event=event)
    assert "Остановлено пользователем" in final.text
