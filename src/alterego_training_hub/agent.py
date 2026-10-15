"""Mentor agent loop: chat + workspace tools with explicit confirmation gates."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

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
    "without waiting for step-by-step instructions. Precision matters more "
    "than speed: act like a jeweller. "
    "Protocol: (1) first inspect what exists (read the relevant files/metrics "
    "before changing anything) and call set_plan with a short checklist of "
    "steps; (2) execute the smallest correct changes, updating the plan as you "
    "go; (3) verify every change (re-read the file, run tests or a short "
    "command, compare metrics) before moving on; (4) if something is wrong in "
    "the model, its config or the running training, fix it with the available "
    "tools (including hot training control via set_training_control). "
    "Use connectors (GitHub/Hugging Face search, e-mail) when they help. "
    "Never claim success without verification. Finish with a short report: "
    "what was done, what was verified, what remains. Answer in the user's "
    "language (Russian unless the user writes in another language)."
)

VERIFY_SYSTEM_PROMPT = (
    "You are a strict reviewer verifying another agent's work on the user's "
    "goal. Use only read-only tools: re-read the changed files, re-run cheap "
    "checks, compare against the goal. Report precisely: (a) what is correct, "
    "(b) any defects, regressions or unverified claims, (c) a verdict: "
    "PASSED or FAILED with reasons. Be picky and concrete. Answer in the "
    "user's language (Russian unless the user writes in another language)."
)

MAX_TOOL_STEPS = 8
AGENT_GOAL_STEPS = 20
VERIFY_STEPS = 4
SUBAGENT_STEPS = 6

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


# Model & training introspection / hot-control tools. The UI supplies the
# implementations; schemas are pure data shared with the agent loop.
MODEL_TOOLS_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_model_info",
            "description": "Полная информация о текущей ЛЛМ: запись каталога, конфиг проекта, "
                           "состояние обучения, метрики, аномалии, горячие параметры (control.json).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_model_catalog",
            "description": "Все модели в каталоге пользователя: id, название, тип, путь/URI, notes.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metrics_history",
            "description": "История метрик обучения: серии loss/acc по эпохам, лучшие значения, "
                           "тренд, аномалии.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"},
                             "description": "Какие метрики вернуть (пусто — все)"},
                    "limit": {"type": "integer", "description": "Максимум точек", "default": 200},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_training_control",
            "description": "Прочитать горячие параметры обучения (control.json): lr, max_epochs, "
                           "early_stop_patience, grad_clip, stop, note.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_training_control",
            "description": "Скорректировать обучение на лету: подправить lr, ограничить число эпох, "
                           "включить раннюю остановку, ограничить градиенты или остановить "
                           "обучение (stop=true). Обучение применяет изменения со следующей эпохи.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lr": {"type": "number", "description": "Новый learning rate"},
                    "max_epochs": {"type": "integer", "description": "Предел эпох"},
                    "early_stop_patience": {"type": "integer",
                                            "description": "Эпох без улучшения до остановки (0 — выкл.)"},
                    "grad_clip": {"type": "number", "description": "Ограничение градиентов (0 — выкл.)"},
                    "stop": {"type": "boolean", "description": "Остановить обучение"},
                    "note": {"type": "string", "description": "Почему применяется корректировка"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_plan",
            "description": "Опубликовать рабочий план (список шагов) — пользователь видит его в "
                           "активности. Обновляйте план по мере продвижения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {"type": "array", "items": {"type": "string"},
                              "description": "Шаги плана (короткие, проверяемые)"},
                },
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Запустить вспомогательного агента на одну узкую подзадачу (только чтение) "
                           "и получить его отчёт. Полезно для параллельных проверок и разведки.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Чёткая подзадача для подагента"},
                    "max_steps": {"type": "integer", "description": "Бюджет шагов (по умолчанию 6)",
                                  "default": 6},
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": "Опубликовать/обновить рабочий план с прогрессом: шаги со "
                           "статусами pending, in_progress, done, failed. "
                           "Обновляй статусы по мере работы.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "status": {"type": "string",
                                       "enum": ["pending", "in_progress",
                                                "done", "failed"]},
                        },
                        "required": ["title"],
                    }},
                },
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_eval_report",
            "description": "Отчёт валидации: perplexity, лучшая эпоха, признаки "
                           "переобучения по eval-метрикам (val_loss/val_acc).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_training_fixes",
            "description": "Предложить изменения гиперпараметров (lr, grad_clip, "
                           "early_stop_patience) на основе метрик и watchdog. "
                           "Только предложения — применяй через set_training_control.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_runs",
            "description": "A/B-сравнение двух последних запусков обучения: "
                           "какой лучше по loss и скорости сходимости.",
            "parameters": {"type": "object", "properties": {
                "key": {"type": "string",
                        "description": "Метрика для наложения графиков, "
                                       "по умолчанию loss"},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_dataset",
            "description": "Отфильтровать и разбить датасет (jsonl/txt/csv/json) "
                           "на train/val/test прямо в рабочей папке. Мутация: "
                           "создаёт файлы <имя>.train.<fmt> и т.д.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Файл датасета в рабочей папке"},
                    "field": {"type": "string", "description": "Текстовое поле (по умолчанию text)"},
                    "contains": {"type": "string", "description": "Оставить строки с подстрокой"},
                    "excludes": {"type": "string", "description": "Убрать строки с подстрокой"},
                    "min_chars": {"type": "integer", "description": "Минимальная длина строки"},
                    "max_chars": {"type": "integer", "description": "Максимальная длина строки"},
                    "train_ratio": {"type": "number", "default": 0.8},
                    "val_ratio": {"type": "number", "default": 0.1},
                    "test_ratio": {"type": "number", "default": 0.1},
                    "seed": {"type": "integer", "default": 42},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_model",
            "description": "Экспорт модели в ONNX или GGUF (конвертация внешним "
                           "инструментом + проверка артефакта). Мутация.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "id модели из каталога"},
                    "source": {"type": "string", "description": "Папка/id модели (если нет model_id)"},
                    "format": {"type": "string", "enum": ["gguf", "onnx"], "default": "gguf"},
                    "out_type": {"type": "string", "description": "Точность GGUF: f32/f16/bf16/q8_0"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quantize_model",
            "description": "Квантизация GGUF-модели (q8_0/q5_k_m/q4_k_m/q4_0/q3_k_m) "
                           "или ONNX (int8) с проверкой размера и качества. Мутация.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "id модели из каталога"},
                    "source": {"type": "string", "description": "Исходный файл (если нет model_id)"},
                    "quant_type": {"type": "string",
                                   "enum": ["q8_0", "q5_k_m", "q4_k_m", "q4_0",
                                            "q3_k_m", "int8"],
                                   "default": "q4_k_m"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "benchmark_model",
            "description": "Бенчмарк модели: замер скорости (мс/запуск, tok/s) "
                           "несколькими прогонами. Мутация (запускает команду).",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "id модели из каталога (с endpoint)"},
                    "command": {"type": "string", "description": "Или своя команда запуска инференса"},
                    "iterations": {"type": "integer", "default": 3},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_prompt_suite",
            "description": "Пакетное тестирование: набор промптов → ответы модели, "
                           "задержки и проверка ожиданий. Расходует токены API. Мутация.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "id модели из каталога (с endpoint)"},
                    "suite_path": {"type": "string", "description": "JSON-набор в рабочей папке (или default)"},
                    "max_tokens": {"type": "integer", "default": 400},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_report",
            "description": "Собрать полный отчёт (модель, метрики, eval, watchdog, "
                           "план, журнал) и сохранить в Markdown/HTML. Мутация.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Куда сохранить (в рабочей папке), "
                                                             "по умолчанию reports/report"},
                    "format": {"type": "string", "enum": ["md", "html", "pdf"], "default": "md"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_cloud_jobs",
            "description": "Показать очередь облачных заданий обучения "
                           "(статусы, pod, ошибки). Только чтение.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_cloud_job",
            "description": "Создать облачное задание (команда обучения) и поставить "
                           "в очередь RunPod. Мутация: может списывать деньги — "
                           "требует подтверждения.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название задания"},
                    "command": {"type": "string", "description": "Команда обучения на машине"},
                    "image": {"type": "string", "description": "Docker-образ (по умолчанию runpod/pytorch)"},
                    "gpu_id": {"type": "string", "description": "ID GPU из каталога RunPod (обязателен для запуска)"},
                    "max_gpu_hourly_usd": {"type": "number", "description": "Лимит цены GPU, $/час"},
                    "container_disk_gb": {"type": "integer", "default": 30},
                },
                "required": ["name", "command"],
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


CLIP_TOOL_CHARS = 1500
KEEP_RECENT_MESSAGES = 6


def compress_messages(messages: list[dict[str, Any]], *,
                      tool_budget: int = CLIP_TOOL_CHARS,
                      total_budget: int = 60_000) -> list[dict[str, Any]]:
    """Keep the conversation compact and precise as the agent works.

    (1) Tool outputs older than the recent window are clipped to
    ``tool_budget`` characters. (2) If the total size still exceeds
    ``total_budget``, the oldest tool payloads are folded into placeholders
    (the last two messages are never touched). System messages stay intact.
    """
    out = [dict(message) for message in messages]
    if not out:
        return out
    start = 1 if out[0].get("role") == "system" else 0
    for index, message in enumerate(out):
        if index < start or index >= len(out) - KEEP_RECENT_MESSAGES:
            continue
        if message.get("role") == "tool":
            content = str(message.get("content") or "")
            if len(content) > tool_budget:
                message["content"] = content[:tool_budget] + " …[обрезано]"
    total = sum(len(str(message.get("content") or "")) for message in out)
    index = start
    while total > total_budget and index < len(out) - 2:
        message = out[index]
        if message.get("role") == "tool":
            content = str(message.get("content") or "")
            if content and not content.startswith("…[результат обрезан"):
                total -= len(content)
                message["content"] = f"…[результат обрезан: {message.get('name', 'tool')}]"
                total += len(message["content"])
        elif message.get("role") in {"user", "assistant"}:
            content = str(message.get("content") or "")
            if len(content) > tool_budget and total > total_budget:
                total -= len(content)
                message["content"] = content[:tool_budget] + " …[обрезано]"
                total += len(message["content"])
        index += 1
    return out


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
        loop_limit: int = 3,
    ):
        self.mentor = mentor
        self.workspace = workspace
        self.max_steps = max(1, int(max_steps))
        self.extra_tools = dict(extra_tools or {})
        self.extra_schemas = list(extra_schemas or [])
        self.extra_mutations = frozenset(extra_mutations or ())
        self.autonomy = autonomy if autonomy in {"assist", "agent"} else "assist"
        self.loop_limit = max(2, int(loop_limit or 3))
        self.enable_tools = bool(enable_tools) and (
            workspace is not None or bool(self.extra_tools)
        )
        self.known_tools = TOOL_NAMES | frozenset(self.extra_tools)
        self._used_mutation = False

    def _readonly_tool_names(self) -> frozenset[str]:
        names = {name for name in TOOL_NAMES if WorkspaceTools.is_readonly(name)}
        names |= {name for name in self.extra_tools
                  if name not in self.extra_mutations}
        return frozenset(names)

    def _parallel_safe(self, call: ToolCall, *, readonly: bool = False) -> bool:
        """Read-only calls may run concurrently; mutations never do."""
        if self.needs_confirmation(call.name):
            return False
        if readonly:
            return True  # mutations are rejected fast inside _execute_call
        if call.name in TOOL_NAMES:
            return WorkspaceTools.is_readonly(call.name)
        if call.name in self.extra_tools:
            return call.name not in self.extra_mutations
        return True  # unknown tool: immediate error dict, no side effects

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
        readonly: bool = False,
        system_extra: str = "",
        cancel_event: Any | None = None,
    ) -> MentorReply:
        """Run one agent turn.

        ``history`` is an OpenAI-style message list (not modified). When a
        ``transcript`` list is provided, every assistant/tool message produced
        during the turn is appended to it for persistence in a chat session.
        In ``readonly`` mode only inspection tools are offered and mutations
        are rejected — used by verification passes and subagents.
        ``system_extra`` appends user-configured instructions to the system
        prompt.
        """
        if system_extra:
            system_prompt = system_prompt + "\n\nAdditional user instructions:\n" + str(system_extra)[:2000]
        messages = [{"role": "system", "content": system_prompt}, *history]
        emit = on_event or (lambda _kind, _payload: None)
        ask_confirm = confirm or (lambda _name, _args, _desc: False)
        last_reply: MentorReply | None = None
        readonly_names = self._readonly_tool_names() if readonly else None
        def cancelled() -> bool:
            return bool(cancel_event is not None
                        and cancel_event.is_set())

        stats = TurnStats()
        guard = LoopGuard(limit=getattr(self, "loop_limit", 3))
        error_streak = 0
        hint_given = False

        for step in range(self.max_steps):
            if cancelled():
                emit("cancelled", {"step": step})
                final = ((last_reply.text if last_reply else "")
                         + "\n\n[Остановлено пользователем.]").strip()
                emit("finished", {"text": final, "stats": stats.as_dict()})
                return MentorReply(
                    text=final,
                    model=last_reply.model if last_reply else self.mentor.model,
                    usage=last_reply.usage if last_reply else {},
                    request_id=last_reply.request_id if last_reply else None)
            if self.enable_tools:
                tool_schemas = WORKSPACE_TOOL_SCHEMAS + self.extra_schemas
                if readonly_names is not None:
                    tool_schemas = [
                        schema for schema in tool_schemas
                        if schema.get("function", {}).get("name") in readonly_names
                    ]
            else:
                tool_schemas = None
            def _note_retry(_attempt: int, category: str) -> None:
                stats.retries += 1
                emit("retry", {"attempt": _attempt, "category": category,
                               "step": step})

            reply = respond_with_retry(
                self.mentor,
                compress_messages(messages),
                tools=tool_schemas,
                max_tokens=max_tokens,
                temperature=temperature,
                on_retry=_note_retry,
            )
            stats.steps = step + 1
            usage = reply.usage or {}
            stats.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            stats.completion_tokens += int(
                usage.get("completion_tokens", 0) or 0)
            text, fallback_calls = extract_text_tool_calls(reply.text)
            calls = list(reply.tool_calls) or fallback_calls
            if fallback_calls and not reply.tool_calls:
                reply = replace(reply, text=text)
            last_reply = reply

            emit("assistant", {"text": reply.text, "tool_calls": len(calls), "step": step})

            if not calls:
                emit("finished", {"text": reply.text, "stats": stats.as_dict()})
                return reply

            assistant_payload = _assistant_payload(reply, calls)
            messages.append(assistant_payload)
            if transcript is not None:
                transcript.append(assistant_payload)
            if cancelled():
                emit("cancelled", {"step": step})
                final = ((reply.text or "")
                         + "\n\n[Остановлено пользователем: запрошенные "
                           "действия не выполнялись.]").strip()
                emit("finished", {"text": final, "stats": stats.as_dict()})
                return MentorReply(text=final, model=reply.model,
                                   usage=reply.usage,
                                   request_id=reply.request_id)
            results = self._execute_calls(calls, ask_confirm, emit,
                                          readonly=readonly)
            for index, call in enumerate(calls):
                result = results[index]
                stats.tool_calls += 1
                ok = bool(result.get("ok"))
                if not ok:
                    stats.tool_errors += 1
                    error_streak += 1
                else:
                    error_streak = 0
                if guard.check(call.name, call.arguments, ok):
                    stats.loop_tripped = True
                    emit("loop_detected", {"name": call.name,
                                           "detail": guard.tripped})
                    note = ("\n\n[Агент остановлен защитой от зацикливания: "
                            + guard.tripped
                            + " Уточните следующее действие.]")
                    final = ((reply.text or "") + note).strip()
                    emit("finished", {"text": final,
                                      "stats": stats.as_dict()})
                    return MentorReply(
                        text=final, model=reply.model, usage=reply.usage,
                        request_id=reply.request_id)
                if error_streak >= 2 and not hint_given:
                    messages.append({"role": "system", "content": RECOVERY_HINT})
                    hint_given = True
                    error_streak = 0
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
        emit("finished", {"text": final_text, "stats": stats.as_dict()})
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
        verify: bool = True,
        system_extra: str = "",
        readonly: bool = False,
        cancel_event: Any | None = None,
    ) -> MentorReply:
        """Autonomous turn: the agent plans, acts, then verifies its own work.

        When ``verify`` is on and the agent mutated anything, one extra
        read-only verification pass reviews the result and its verdict is
        appended to the final report. ``readonly`` forces read-only tools
        (guest access mode).
        """
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must not be empty")
        self._used_mutation = False
        reply = self.run_turn(
            [{"role": "user", "content": goal}],
            confirm=confirm,
            on_event=on_event,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=AGENT_GOAL_SYSTEM_PROMPT,
            transcript=transcript,
            system_extra=system_extra,
            readonly=readonly,
            cancel_event=cancel_event,
        )
        if not verify or not self._used_mutation:
            return reply
        emit = on_event or (lambda _kind, _payload: None)
        emit("info", {"text": "Самопроверка результата…"})
        verification = self.run_turn(
            [{
                "role": "user",
                "content": (
                    f"Цель пользователя: {goal}\n\n"
                    f"Отчёт исполнителя:\n{reply.text or '(без текста)'}\n\n"
                    "Проверь результат по цели и инструментам и вынеси вердикт."
                ),
            }],
            on_event=on_event,
            max_tokens=min(max_tokens, 900),
            temperature=0.0,
            system_prompt=VERIFY_SYSTEM_PROMPT,
            readonly=True,
        )
        final_text = (
            (reply.text or "").rstrip()
            + "\n\n--- Самопроверка ---\n"
            + (verification.text or "").strip()
        ).strip()
        emit("finished", {"text": final_text})
        return MentorReply(
            text=final_text,
            model=reply.model,
            usage=reply.usage,
            request_id=reply.request_id,
        )

    def _execute_calls(
        self,
        calls: list[ToolCall],
        confirm: ConfirmFn,
        emit: EventFn,
        *,
        readonly: bool = False,
    ) -> list[dict[str, Any]]:
        """Execute one model block: parallel readonly runs, ordered results.

        Consecutive parallel-safe calls (reads/searches/diffs and read-only
        context tools) run on a small thread pool; mutations and anything
        needing confirmation flush the batch and run one-by-one, so side
        effects stay strictly sequential and dialogues never race.
        """
        results: list[dict[str, Any] | None] = [None] * len(calls)
        index = 0
        while index < len(calls):
            if not self._parallel_safe(calls[index], readonly=readonly):
                results[index] = self._execute_call(
                    calls[index], index, confirm, emit, readonly=readonly)
                index += 1
                continue
            end = index
            while end < len(calls) and self._parallel_safe(
                    calls[end], readonly=readonly):
                end += 1
            batch = list(range(index, end))
            if len(batch) == 1:
                only = batch[0]
                results[only] = self._execute_call(
                    calls[only], only, confirm, emit, readonly=readonly)
            else:
                emit("parallel_batch", {"count": len(batch),
                                        "names": [calls[i].name
                                                  for i in batch]})
                from concurrent.futures import ThreadPoolExecutor

                def run_one(i: int) -> dict[str, Any]:
                    return self._execute_call(
                        calls[i], i, confirm, emit, readonly=readonly)

                with ThreadPoolExecutor(max_workers=min(4, len(batch)),
                                        thread_name_prefix="agent-ro") as pool:
                    for i, result in zip(batch, pool.map(run_one, batch)):
                        results[i] = result
            index = end
        return [result if result is not None else
                {"ok": False, "error": "no result"} for result in results]

    def _execute_call(
        self,
        call: ToolCall,
        index: int,
        confirm: ConfirmFn,
        emit: EventFn,
        *,
        readonly: bool = False,
    ) -> dict[str, Any]:
        description = _describe(call)
        if (self.workspace is not None and self.needs_confirmation(call.name)):
            diff = self.workspace.preview_change(call.name, call.arguments)
            if diff and diff != "(без изменений)":
                description += "\n\nПредпросмотр изменений:\n" + diff
        emit("tool_start", {"name": call.name, "arguments": call.arguments,
                            "description": description, "index": index})
        if readonly and (call.name in self.extra_mutations
                         or (call.name in TOOL_NAMES
                             and not WorkspaceTools.is_readonly(call.name))):
            result = {
                "ok": False,
                "error": "Инструмент недоступен: режим только для чтения.",
            }
            emit("tool_result", {"name": call.name, "ok": False,
                                 "summary": _summarize(result), "index": index})
            return result
        if call.name in self.extra_tools:
            # Context tools: read-only run freely; mutations respect autonomy.
            try:
                if self.needs_confirmation(call.name):
                    try:
                        approved = bool(confirm(call.name, call.arguments, description))
                    except Exception:
                        approved = False
                    if not approved:
                        result = {
                            "ok": False, "error": "Действие отклонено пользователем."}
                    else:
                        result = self.extra_tools[call.name](call.arguments or {})
                else:
                    result = self.extra_tools[call.name](call.arguments or {})
                if not isinstance(result, dict):
                    result = {"ok": True, "result": str(result)}
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        elif call.name not in TOOL_NAMES:
            result = {"ok": False, "error": f"Неизвестный инструмент: {call.name}"}
        elif self.workspace is None:
            result = {"ok": False, "error": "Рабочая папка не подключена."}
        elif self.needs_confirmation(call.name):
            try:
                approved = bool(confirm(call.name, call.arguments, description))
            except Exception:
                approved = False
            if not approved:
                result = {"ok": False, "error": "Действие отклонено пользователем."}
            else:
                result = self.workspace.execute(call.name, call.arguments)
        else:
            result = self.workspace.execute(call.name, call.arguments)
        emit("tool_result", {"name": call.name, "ok": bool(result.get("ok")),
                             "summary": _summarize(result), "index": index})
        if result.get("ok") and (
            call.name in self.extra_mutations
            or (call.name in TOOL_NAMES and not WorkspaceTools.is_readonly(call.name))
        ):
            self._used_mutation = True
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
        "get_model_info": "Полная информация о текущей ЛЛМ",
        "list_model_catalog": "Каталог моделей",
        "get_metrics_history": "История метрик обучения",
        "get_training_control": "Горячие параметры обучения",
        "set_training_control": "Скорректировать обучение на лету",
        "set_plan": "Опубликовать рабочий план",
        "update_plan": "Обновить план и статусы шагов",
        "spawn_subagent": "Запустить подагента на подзадачу",
        "get_eval_report": "Отчёт валидации (perplexity/переобучение)",
        "suggest_training_fixes": "Предложить правки гиперпараметров",
        "compare_runs": "A/B-сравнение запусков обучения",
        "prepare_dataset": "Фильтр и разбиение датасета на train/val/test",
        "export_model": "Экспорт модели (ONNX/GGUF)",
        "quantize_model": "Квантизация модели",
        "benchmark_model": "Бенчмарк скорости модели",
        "run_prompt_suite": "Пакетное тестирование промптов",
        "export_report": "Экспорт полного отчёта (Markdown/HTML)",
        "list_cloud_jobs": "Очередь облачных заданий",
        "submit_cloud_job": "Поставить задание в облако (RunPod)",
    }
    base = descriptions.get(call.name, call.name)
    if call.name == "send_email":
        return f"{base}: → {call.arguments.get('to', '')} «{call.arguments.get('subject', '')}»"
    if call.name in {"search_github", "search_huggingface"}:
        return f"{base}: {call.arguments.get('query', '')}"
    if call.name == "update_plan":
        steps = call.arguments.get("steps") or []
        return f"{base}: шагов — {len(steps)}"
    return base


def _summarize(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"ошибка: {result.get('error', 'неизвестно')}"
    summary = json.dumps({k: v for k, v in result.items() if k != "content"},
                         ensure_ascii=False)
    return summary[:240]


# ============================================================ этап 30: надёжность

_TRANSIENT_MARKERS = (
    "timeout", "timed out", "temporarily", "connection", "network",
    "429", "rate limit", "502", "503", "504", "overloaded", "eof occurred",
)
_PERMISSION_MARKERS = ("permission", "403", "unauthorized", "401", "api key",
                       "доступ запрещ", "отклонено пользователем")
_NOT_FOUND_MARKERS = ("not found", "no such file", "404", "не найден", "не существует")
_VALIDATION_MARKERS = ("invalid", "validation", "некоррект", "недопустим",
                       "must be", "required", "обязател")


def classify_error(exc_or_text: Any) -> str:
    """Classify an error: transient|permission|not_found|validation|fatal."""
    if isinstance(exc_or_text, (TimeoutError, ConnectionError)):
        return "transient"
    text = str((getattr(exc_or_text, "args", None) and exc_or_text) or exc_or_text).lower()
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return "transient"
    if any(marker in text for marker in _PERMISSION_MARKERS):
        return "permission"
    if any(marker in text for marker in _NOT_FOUND_MARKERS):
        return "not_found"
    if any(marker in text for marker in _VALIDATION_MARKERS):
        return "validation"
    return "fatal"


def is_transient(exc: Any) -> bool:
    return classify_error(exc) == "transient"


@dataclass
class LoopGuard:
    """Detects the agent repeating the same call with the same outcome."""

    limit: int = 3
    _counts: dict[str, int] = field(default_factory=dict)
    tripped: str = ""

    @staticmethod
    def signature(name: str, arguments: dict[str, Any], ok: bool) -> str:
        raw = json.dumps({"t": name, "a": arguments or {}, "ok": ok},
                         ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def check(self, name: str, arguments: dict[str, Any], ok: bool) -> bool:
        """Record one outcome; True when the repeat limit is exceeded."""
        sig = self.signature(name, arguments, ok)
        self._counts[sig] = self._counts.get(sig, 0) + 1
        if self._counts[sig] >= max(2, int(self.limit)):
            self.tripped = (f"Вызов {name} с теми же аргументами повторялся "
                            f"{self._counts[sig]} раз с одинаковым исходом.")
            return True
        return False

    def repeats(self) -> int:
        return max(self._counts.values(), default=0)


@dataclass
class TurnStats:
    """Measurable quality of one agent turn (этап 30)."""

    steps: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    retries: int = 0
    loop_tripped: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    started_at: float = field(default_factory=time.time)

    @property
    def seconds(self) -> float:
        return round(time.time() - self.started_at, 2)

    def as_dict(self) -> dict[str, Any]:
        return {"steps": self.steps, "tool_calls": self.tool_calls,
                "tool_errors": self.tool_errors, "retries": self.retries,
                "loop_tripped": self.loop_tripped,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "seconds": self.seconds}

    def render(self) -> str:
        rows = (f"Шагов: {self.steps} · вызовов: {self.tool_calls} · "
                f"ошибок: {self.tool_errors} · повторов сети: {self.retries} · "
                f"токены: {self.prompt_tokens}→{self.completion_tokens} · "
                f"{self.seconds:.1f} c")
        return rows


def respond_with_retry(mentor: Any, messages: list[dict[str, Any]], *,
                       tools: Any = None, max_tokens: int = 1200,
                       temperature: float = 0.2, attempts: int = 3,
                       sleep: Callable[[float], None] | None = None,
                       on_retry: Callable[[int, str], None] | None = None,
                       ) -> MentorReply:
    """mentor.respond with backoff on transient provider errors only."""
    wait = sleep or time.sleep
    last_exc: Exception | None = None
    for attempt in range(max(1, int(attempts))):
        try:
            return mentor.respond(messages, tools=tools,
                                  max_tokens=max_tokens, temperature=temperature)
        except Exception as exc:
            last_exc = exc
            if not is_transient(exc) or attempt >= max(1, int(attempts)) - 1:
                raise
            if on_retry is not None:
                on_retry(attempt + 1, classify_error(exc))
            wait(min(8.0, 0.5 * (2 ** attempt)))
    assert last_exc is not None  # pragma: no cover - loop invariant
    raise last_exc


RECOVERY_HINT = (
    "[Система: последние вызовы инструментов завершились ошибками. "
    "Не повторяй тот же вызов. Перечитай релевантный файл/лог, проверь "
    "аргументы и смени подход: другой инструмент, меньший шаг или уточни "
    "у пользователя, если данных не хватает.]"
)
