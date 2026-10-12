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

MAX_TOOL_STEPS = 8

# Fallback instruction protocol for providers without native function calling.
# The model can emit a fenced block:
#   ```tool
#   {"name": "read_file", "arguments": {"path": "src/app.py"}}
#   ```
TOOL_BLOCK_RE = re.compile(r"```tool\s*\n(\{.*?\})\s*\n```", re.DOTALL)

ConfirmFn = Callable[[str, dict[str, Any], str], bool]
EventFn = Callable[[str, dict[str, Any]], None]


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
    ):
        self.mentor = mentor
        self.workspace = workspace
        self.max_steps = max(1, int(max_steps))
        self.enable_tools = bool(enable_tools) and workspace is not None

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
            reply = self.mentor.respond(
                messages,
                tools=WORKSPACE_TOOL_SCHEMAS if self.enable_tools else None,
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
        if call.name not in TOOL_NAMES:
            result: dict[str, Any] = {"ok": False, "error": f"Неизвестный инструмент: {call.name}"}
        elif self.workspace is None:
            result = {"ok": False, "error": "Рабочая папка не подключена."}
        elif not WorkspaceTools.is_readonly(call.name):
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
    from .tools import WorkspaceTools

    return WorkspaceTools.describe(call.name, call.arguments)


def _summarize(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"ошибка: {result.get('error', 'неизвестно')}"
    summary = json.dumps({k: v for k, v in result.items() if k != "content"},
                         ensure_ascii=False)
    return summary[:240]
