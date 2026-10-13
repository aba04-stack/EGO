"""Mentor agent loop: chat + workspace tools with explicit confirmation gates."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Callable

from .mentor import ApiMentor, MentorReply, ToolCall
from .tools import TOOL_NAMES, WORKSPACE_TOOL_SCHEMAS, WorkspaceTools

DEFAULT_AGENT_SYSTEM_PROMPT = (
    "You are a careful AI research mentor and coding assistant working inside "
    "the user's project workspace. You can inspect and edit files, search code, "
    "and run commands through the provided tools. "
    "Separate verified facts from hypotheses, state uncertainty, and recommend "
    "measurable tests. When fixing code, first read the relevant files, then make "
    "the smallest change that fixes the problem, then verify it (run tests or a "
    "short command). Write explanations in the user's language (Russian unless "
    "the user writes in another language)."
)

AGENT_GOAL_SYSTEM_PROMPT = (
    "You are an autonomous engineering agent. Work towards the user's goal "
    "without waiting for step-by-step instructions: plan, use tools to inspect "
    "the workspace, make changes, and verify results with commands or tests. "
    "Use connectors (GitHub/Hugging Face search, e-mail) when they help. "
    "After each action, check the result and continue until the goal is done "
    "or you need a human decision. Finish with a short report: what was done, "
    "what was verified, what remains. Answer in the user's language (Russian "
    "unless the user writes in another language)."
)

MAX_TOOL_STEPS = 8
AGENT_GOAL_STEPS = 14

# Fallback instruction protocol for providers without native function calling.
# The model can emit a fenced block:
#   ```tool
#   {"name": "read_file", "arguments": {"path": "src/app.py"}}
#   ```
TOOL_BLOCK_RE = re.compile(r"```tool\s*\n(\{.*?\})\s*\n```", re.DOTALL)

ConfirmFn = Callable[[str, dict[str, Any], str], bool]
EventFn = Callable[[str, dict[str, Any]], None]

# Read-only context tools: the mentor can inspect training progress even
# without a workspace. The UI supplies the implementations.
TRAINING_CONTEXT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_training_status",
            "description": "Состояние текущего/последнего обучения: команда, код возврата, "
                           "метрики, аномалии, прогресс эпох.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_training_log",
            "description": "Хвост лога текущего/последнего обучения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_bytes": {"type": "integer", "description": "Сколько байт хвоста",
                                  "default": 8000},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_run_history",
            "description": "Последние запуски обучения: статус, код возврата, метрики, оценка.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Сколько запусков", "default": 5},
                },
                "required": [],
            },
        },
    },
]


def extract_text_tool_calls(text: str) -> tuple[str, list[ToolCall]]:
    """Parse fallback tool blocks out of plain text replies."""
    calls: list[ToolCall] = []

    def replace_block(match: re.Match[str]) -> str:
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return match.group(0)  # leave malformed block visible to the user
        name = str(payload.get("name") or "")
        arguments = payload.get("arguments", payload.get("args", {}))
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(id=f"text-call-{len(calls) + 1}", name=name, arguments=arguments))
        return ""

    cleaned = TOOL_BLOCK_RE.sub(replace_block, text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip(), calls


class MentorAgent:
    """Drives a multi-step turn: mentor reply -> tool calls -> results -> reply."""

    def __init__(
        self,
        mentor: ApiMentor,
        workspace: WorkspaceTools | None = None,
        *,
        max_steps: int = MAX_TOOL_STEPS,
        enable_tools: bool = True,
        extra_tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
        extra_schemas: list[dict[str, Any]] | None = None,
        extra_mutations: frozenset[str] | set[str] | None = None,
        autonomy: str = "assist",
    ):
        self.mentor = mentor
        self.workspace = workspace
        self.max_steps = max(1, int(max_steps))
        self.extra_tools = dict(extra_tools or {})
        self.extra_schemas = list(extra_schemas or [])
        self.extra_mutations = frozenset(extra_mutations or ())
        self.autonomy = autonomy if autonomy in {"assist", "agent"} else "assist"
        self.enable_tools = bool(enable_tools) and (
            workspace is not None or bool(self.extra_tools)
        )
        self.known_tools = TOOL_NAMES | frozenset(self.extra_tools)

    def needs_confirmation(self, name: str) -> bool:
        """In agent autonomy mode actions run freely (still backed up/logged)."""
        if self.autonomy == "agent":
            return False
        if name in self.extra_mutations:
            return True
        return name in TOOL_NAMES and not WorkspaceTools.is_readonly(name)

    def run_turn(
        self,
        history: list[dict[str, Any]],
        *,
        confirm: ConfirmFn | None = None,
        on_event: EventFn | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.2,
        system_prompt: str = DEFAULT_AGENT_SYSTEM_PROMPT,
        transcript: list[dict[str, Any]] | None = None,
    ) -> MentorReply:
        """Run one agent turn.

        ``history`` is an OpenAI-style message list (not modified). When a
        ``transcript`` list is provided, every assistant/tool message produced
        during the turn is appended to it for persistence in a chat session.
        """
        messages = [{"role": "system", "content": system_prompt}, *history]
        emit = on_event or (lambda _kind, _payload: None)
        ask_confirm = confirm or (lambda _name, _args, _desc: False)
        last_reply: MentorReply | None = None

        for step in range(self.max_steps):
            tool_schemas = (
                WORKSPACE_TOOL_SCHEMAS + self.extra_schemas
                if self.enable_tools else None
            )
            reply = self.mentor.respond(
                messages,
                tools=tool_schemas,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text, fallback_calls = extract_text_tool_calls(reply.text)
            calls = list(reply.tool_calls) or fallback_calls
            if fallback_calls and not reply.tool_calls:
                reply = replace(reply, text=text)
            last_reply = reply

            emit("assistant", {"text": reply.text, "tool_calls": len(calls), "step": step})

            if not calls:
                emit("finished", {"text": reply.text})
                return reply

            assistant_payload = _assistant_payload(reply, calls)
            messages.append(assistant_payload)
            if transcript is not None:
                transcript.append(assistant_payload)
            for index, call in enumerate(calls):
                result = self._execute_call(call, index, ask_confirm, emit)
                tool_payload = {
                    "role": "tool",
                    "tool_call_id": call.id or f"call-{step}-{index}",
                    "name": call.name,
                    "content": json.dumps(result, ensure_ascii=False)[:8000],
                }
                messages.append(tool_payload)
                if transcript is not None:
                    transcript.append(tool_payload)

        note = "\n\n[Достигнут лимит шагов инструментов — уточните следующее действие.]"
        final_text = ((last_reply.text if last_reply else "") + note).strip()
        emit("finished", {"text": final_text})
        return MentorReply(
            text=final_text,
            model=last_reply.model if last_reply else self.mentor.model,
            usage=last_reply.usage if last_reply else {},
            request_id=last_reply.request_id if last_reply else None,
        )

    def run_goal(
        self,
        goal: str,
        *,
        confirm: ConfirmFn | None = None,
        on_event: EventFn | None = None,
        max_tokens: int = 1600,
        temperature: float = 0.2,
        transcript: list[dict[str, Any]] | None = None,
    ) -> MentorReply:
        """Autonomous turn: the agent plans and acts until the goal is done."""
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must not be empty")
        return self.run_turn(
            [{"role": "user", "content": goal}],
            confirm=confirm,
            on_event=on_event,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=AGENT_GOAL_SYSTEM_PROMPT,
            transcript=transcript,
        )

    def _execute_call(
        self,
        call: ToolCall,
        index: int,
        confirm: ConfirmFn,
        emit: EventFn,
    ) -> dict[str, Any]:
        description = _describe(call)
        emit("tool_start", {"name": call.name, "arguments": call.arguments,
                            "description": description, "index": index})
        if call.name in self.extra_tools:
            # Context tools: read-only run freely; mutations respect autonomy.
            try:
                if self.needs_confirmation(call.name):
                    try:
                        approved = bool(confirm(call.name, call.arguments, description))
                    except Exception:  # noqa: BLE001 - a broken dialog must not run mutations
                        approved = False
                    if not approved:
                        result: dict[str, Any] = {
                            "ok": False, "error": "Действие отклонено пользователем."}
                    else:
                        result = self.extra_tools[call.name](call.arguments or {})
                else:
                    result = self.extra_tools[call.name](call.arguments or {})
                if not isinstance(result, dict):
                    result = {"ok": True, "result": str(result)}
            except Exception as exc:  # noqa: BLE001 - tool boundary must not crash
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        elif call.name not in TOOL_NAMES:
            result = {"ok": False, "error": f"Неизвестный инструмент: {call.name}"}
        elif self.workspace is None:
            result = {"ok": False, "error": "Рабочая папка не подключена."}
        elif self.needs_confirmation(call.name):
            try:
                approved = bool(confirm(call.name, call.arguments, description))
            except Exception:  # noqa: BLE001 - a broken dialog must not run mutations
                approved = False
            if not approved:
                result = {"ok": False, "error": "Действие отклонено пользователем."}
            else:
                result = self.workspace.execute(call.name, call.arguments)
        else:
            result = self.workspace.execute(call.name, call.arguments)
        emit("tool_result", {"name": call.name, "ok": bool(result.get("ok")),
                             "summary": _summarize(result), "index": index})
        return result


def _assistant_payload(reply: MentorReply, calls: list[ToolCall]) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": "assistant", "content": reply.text or None}
    payload["tool_calls"] = [
        {
            "id": call.id or f"call-{index}",
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False),
            },
        }
        for index, call in enumerate(calls)
    ]
    return payload


def _describe(call: ToolCall) -> str:
    from .tools import TOOL_DESCRIPTIONS_RU, WorkspaceTools

    if call.name in TOOL_DESCRIPTIONS_RU:
        return WorkspaceTools.describe(call.name, call.arguments)
    descriptions = {
        "get_training_status": "Состояние текущего обучения и метрики",
        "read_training_log": "Прочитать лог обучения",
        "get_run_history": "История запусков обучения",
        "start_training": "Запустить обучение",
        "stop_training": "Остановить обучение",
        "run_diagnostics": "Проверка окружения (диагностика)",
        "search_github": "Поиск репозиториев на GitHub",
        "search_huggingface": "Поиск моделей на Hugging Face",
        "huggingface_model_card": "Карточка модели Hugging Face",
        "send_email": "Отправить письмо (email)",
        "list_servers": "Список серверов",
        "server_info": "Информация о сервере",
        "run_on_server": "Команда на сервере",
    }
    base = descriptions.get(call.name, call.name)
    if call.name == "send_email":
        return f"{base}: → {call.arguments.get('to', '')} «{call.arguments.get('subject', '')}»"
    if call.name in {"search_github", "search_huggingface"}:
        return f"{base}: {call.arguments.get('query', '')}"
    return base


def _summarize(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"ошибка: {result.get('error', 'неизвестно')}"
    summary = json.dumps({k: v for k, v in result.items() if k != "content"},
                         ensure_ascii=False)
    return summary[:240]
