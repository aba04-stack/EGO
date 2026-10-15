"""Tests for agent precision: context compression, readonly mode, verify pass."""
from __future__ import annotations

from alterego_training_hub.agent import (
    MODEL_TOOLS_SCHEMAS,
    MentorAgent,
    compress_messages,
)


class _Reply:
    def __init__(self, text, tool_calls=()):
        self.text = text
        self.tool_calls = tuple(tool_calls)
        self.model = "fake"
        self.usage = {}
        self.request_id = None


class _Call:
    def __init__(self, name, arguments):
        self.id = f"call-{name}"
        self.name = name
        self.arguments = arguments


class FakeMentor:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen_tools = []
        self.seen_messages = []

    def respond(self, messages, *, tools=None, max_tokens=700, temperature=0.2):
        self.seen_messages.append(messages)
        self.seen_tools.append([t.get("function", {}).get("name")
                                for t in (tools or [])])
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]


def test_compress_messages_clips_old_tool_output():
    messages = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "goal"}]
    for index in range(8):
        messages.append({"role": "tool", "name": "read_file",
                         "content": "x" * 5000 + str(index)})
    compressed = compress_messages(messages, tool_budget=100,
                                   total_budget=20000)
    tool_contents = [m["content"] for m in compressed if m.get("role") == "tool"]
    # Pass 1 clips tool outputs outside the recent window.
    assert all(len(content) <= 120 for content in tool_contents[:2])
    # Pass 2 folds the oldest payloads until under the total budget.
    assert any(content.startswith("…[результат обрезан")
               for content in tool_contents)
    assert compressed[0]["content"] == "sys"  # system intact
    total = sum(len(str(m.get("content") or "")) for m in compressed)
    assert total <= 20000 + 400  # placeholder overhead tolerance


def test_readonly_mode_blocks_mutations(tmp_path):
    from alterego_training_hub.tools import WorkspaceTools

    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    workspace = WorkspaceTools(root)

    mentor = FakeMentor([
        _Reply("", [_Call("write_file", {"path": "a.txt", "content": "hack"})]),
        _Reply("Закончил."),
    ])
    agent = MentorAgent(mentor, workspace, max_steps=3)
    reply = agent.run_turn([{"role": "user", "content": "измени"}],
                           readonly=True)
    assert (root / "a.txt").read_text(encoding="utf-8") == "hello"  # untouched
    assert reply.text == "Закончил."

    # Non-readonly mode performs the same write in agent autonomy.
    mentor2 = FakeMentor([
        _Reply("", [_Call("write_file", {"path": "a.txt", "content": "ok"})]),
        _Reply("Готово."),
    ])
    agent2 = MentorAgent(mentor2, workspace, max_steps=3, autonomy="agent")
    agent2.run_turn([{"role": "user", "content": "измени"}])
    assert (root / "a.txt").read_text(encoding="utf-8") == "ok"


def test_verify_pass_appends_verdict_after_mutation(tmp_path):
    from alterego_training_hub.tools import WorkspaceTools

    root = tmp_path / "ws"
    root.mkdir()
    workspace = WorkspaceTools(root)
    mentor = FakeMentor([
        _Reply("", [_Call("write_file", {"path": "b.txt", "content": "data"})]),
        _Reply("Файл создан."),
        _Reply("Проверил: файл на месте. Вердикт: PASSED."),
    ])
    agent = MentorAgent(mentor, workspace, max_steps=5, autonomy="agent")
    reply = agent.run_goal("создай b.txt", verify=True)
    assert "Файл создан." in reply.text
    assert "Самопроверка" in reply.text
    assert "PASSED" in reply.text
    # Verification turn ran with read-only tool subset.
    assert "write_file" not in mentor.seen_tools[-1]


def test_run_goal_without_mutation_skips_verify(tmp_path):
    mentor = FakeMentor([_Reply("Просто ответ.")])
    agent = MentorAgent(mentor, max_steps=3)
    reply = agent.run_goal("объясни", verify=True)
    assert reply.text == "Просто ответ."
    assert len(mentor.seen_messages) == 1


def test_model_tool_schemas_are_unique_and_named():
    names = [schema["function"]["name"] for schema in MODEL_TOOLS_SCHEMAS]
    assert len(names) == len(set(names))
    for expected in ("get_model_info", "set_training_control", "set_plan",
                     "spawn_subagent", "get_metrics_history"):
        assert expected in names


def test_system_extra_is_applied():
    mentor = FakeMentor([_Reply("ok")])
    agent = MentorAgent(mentor, max_steps=2)
    agent.run_turn([{"role": "user", "content": "hi"}],
                   system_extra="Всегда пиши по-русски.")
    sent = mentor.seen_messages[0][0]
    assert sent["role"] == "system"
    assert "Всегда пиши по-русски." in sent["content"]
