import json

from alterego_training_hub.agent import MentorAgent, extract_text_tool_calls
from alterego_training_hub.mentor import MentorReply, ToolCall
from alterego_training_hub.tools import WorkspaceTools


class FakeMentor:
    """Scripted mentor: returns queued replies, records request history."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.model = "fake-model"

    def respond(self, messages, *, tools=None, max_tokens=700, temperature=0.2):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


def reply(text="", calls=()):
    return MentorReply(text=text, model="fake-model", usage={"total_tokens": 1},
                       tool_calls=tuple(calls))


def test_extract_text_tool_calls_fallback_protocol():
    text = (
        "Посмотрю файл.\n"
        "```tool\n"
        '{"name": "read_file", "arguments": {"path": "src/app.py"}}\n'
        "```\n"
    )
    cleaned, calls = extract_text_tool_calls(text)
    assert "```tool" not in cleaned
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "src/app.py"}


def test_agent_runs_readonly_tool_and_finishes(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    workspace = WorkspaceTools(tmp_path)
    mentor = FakeMentor([
        reply("Прочитаю.", calls=[ToolCall("c1", "read_file", {"path": "a.py"})]),
        reply("Файл прочитан, всё ок."),
    ])
    events = []
    agent = MentorAgent(mentor, workspace)
    final = agent.run_turn(
        [{"role": "user", "content": "проверь a.py"}],
        on_event=lambda kind, payload: events.append(kind),
    )
    assert final.text == "Файл прочитан, всё ок."
    kinds = events
    assert "tool_start" in kinds and "tool_result" in kinds and "finished" in kinds
    # second request must include the tool result message
    tool_messages = [m for m in mentor.requests[1]["messages"] if m["role"] == "tool"]
    assert tool_messages and tool_messages[0]["name"] == "read_file"
    assert json.loads(tool_messages[0]["content"])["ok"] is True


def test_agent_requires_confirmation_for_mutations(tmp_path):
    workspace = WorkspaceTools(tmp_path)
    mentor = FakeMentor([
        reply("Перепишу.", calls=[ToolCall("c1", "write_file", {"path": "x.py", "content": "z"})]),
        reply("Готово."),
    ])
    agent = MentorAgent(mentor, workspace)
    # no confirm callback -> mutations denied
    final = agent.run_turn([{"role": "user", "content": "исправь"}])
    assert final.text == "Готово."
    assert not (tmp_path / "x.py").exists()
    # the denial was reported back to the model
    tool_messages = [m for m in mentor.requests[1]["messages"] if m["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"])["ok"] is False

    mentor2 = FakeMentor([
        reply("", calls=[ToolCall("c1", "write_file", {"path": "y.py", "content": "ok"})]),
        reply("Записал."),
    ])
    agent2 = MentorAgent(mentor2, workspace)
    agent2.run_turn([{"role": "user", "content": "сделай"}],
                    confirm=lambda name, args, desc: True)
    assert (tmp_path / "y.py").read_text(encoding="utf-8") == "ok"


def test_agent_handles_unknown_tool_and_step_limit(tmp_path):
    workspace = WorkspaceTools(tmp_path)
    mentor = FakeMentor([
        reply("", calls=[ToolCall("c1", "drop_database", {})]),
        reply("ладно"),
    ])
    agent = MentorAgent(mentor, workspace)
    final = agent.run_turn([{"role": "user", "content": "го"}])
    assert final.text == "ладно"
    tool_messages = [m for m in mentor.requests[1]["messages"] if m["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"])["ok"] is False

    always_calling = FakeMentor(
        [reply("", calls=[ToolCall(f"c{i}", "list_files", {})]) for i in range(10)]
    )
    agent2 = MentorAgent(always_calling, workspace, max_steps=2)
    final2 = agent2.run_turn([{"role": "user", "content": "цикл"}])
    assert "лимит шагов" in final2.text


def test_agent_without_workspace_still_chats():
    mentor = FakeMentor([reply("Просто отвечаю.")])
    agent = MentorAgent(mentor, None)
    final = agent.run_turn([{"role": "user", "content": "привет"}])
    assert final.text == "Просто отвечаю."
    assert mentor.requests[0]["tools"] is None


def test_agent_extra_context_tools(tmp_path):
    calls = []

    def status_tool(args):
        calls.append(args)
        return {"ok": True, "running": True, "metrics": {"loss": 0.5}}

    mentor = FakeMentor([
        reply("", calls=[ToolCall("c1", "get_training_status", {})]),
        reply("Обучение идёт."),
    ])
    agent = MentorAgent(
        mentor, None,
        extra_tools={"get_training_status": status_tool},
        extra_schemas=[{"type": "function",
                        "function": {"name": "get_training_status", "parameters": {}}}],
    )
    final = agent.run_turn([{"role": "user", "content": "как обучение?"}])
    assert final.text == "Обучение идёт."
    assert calls and calls[0] == {}
    # extra tools are advertised and executed without a workspace
    assert mentor.requests[0]["tools"] is not None
    tool_messages = [m for m in mentor.requests[1]["messages"] if m["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"])["running"] is True


def test_workspace_write_creates_backup(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("old\n", encoding="utf-8")
    workspace = WorkspaceTools(tmp_path, backup_dir=tmp_path / "backups")

    result = workspace.execute("write_file", {"path": "src/app.py", "content": "new\n"})
    assert result["ok"] is True
    backup = result["backup"]
    assert backup.endswith("app.py")
    assert open(backup, encoding="utf-8").read() == "old\n"

    result2 = workspace.execute(
        "replace_in_file", {"path": "src/app.py", "find": "new", "replace": "newer"})
    assert result2["ok"] is True
    assert result2["backup"] != backup
