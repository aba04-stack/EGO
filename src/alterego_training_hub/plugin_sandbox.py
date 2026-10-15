"""Sandbox for untrusted plugins: run their code in a restricted subprocess.

Trust model
-----------
* ``trusted`` plugins (``PLUGIN["trusted"] = True``, detected statically via
  AST — no code runs in-process) load and execute in-process.
* Everything else is **sandboxed**: the plugin file is executed inside a
  worker subprocess with restricted builtins (a small import whitelist, no
  ``open``/``os``/``subprocess``/``socket``), a wall-clock timeout and, on
  POSIX, a memory cap. The worker speaks JSON over stdin/stdout.

The sandbox raises the bar against buggy or malicious plugins; it is not a
hard OS-level jail. Review code before marking a plugin trusted.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 15.0
DEFAULT_MEMORY_MB = 256


class SandboxError(RuntimeError):
    """Sandbox violation or transport error safe to display."""


def static_trusted(path: str | Path) -> bool:
    """True only when the source sets ``PLUGIN = {..., "trusted": True}``."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [target.id for target in node.targets
                   if isinstance(target, ast.Name)]
        if "PLUGIN" not in targets or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if (isinstance(key, ast.Constant) and key.value == "trusted"
                    and isinstance(value, ast.Constant)
                    and value.value is True):
                return True
    return False


def build_meta(payload: dict, path: str | Path) -> tuple[dict, str]:
    """Validate a PLUGIN payload and return (meta, error).

    ``meta`` is JSON-safe: ids, schemas and mutation flags — never handlers.
    Error strings match the in-process loader so UX is identical.
    """
    plugin_id = str(payload.get("id") or Path(path).stem).strip() \
        or Path(path).stem
    meta: dict[str, Any] = {
        "id": plugin_id,
        "name": str(payload.get("name") or plugin_id),
        "version": str(payload.get("version") or "0"),
        "description": str(payload.get("description") or ""),
        "trusted": bool(payload.get("trusted")),
        "tools": [],
    }
    tools = payload.get("tools") or {}
    if not isinstance(tools, dict):
        return meta, "поле tools должно быть словарём"
    for name, spec in tools.items():
        if not isinstance(spec, dict):
            return meta, f"инструмент «{name}» описан не объектом"
        schema = spec.get("schema")
        handler = spec.get("handler")
        function = (schema or {}).get("function", {}) if isinstance(
            schema, dict) else {}
        if not isinstance(schema, dict) or not function.get("name") \
                or not callable(handler):
            return meta, (f"инструмент «{name}»: нужен schema.function.name "
                          "и handler")
        meta["tools"].append({
            "name": str(function.get("name")),
            "schema": schema,
            "mutation": bool(spec.get("mutation")),
        })
    return meta, ""


def _worker(request: dict, *, timeout: float, memory_mb: int) -> dict:
    """Run one request in the sandbox worker subprocess."""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "alterego_training_hub.plugin_worker",
             "--memory-mb", str(int(memory_mb))],
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True, text=True, timeout=max(1.0, float(timeout)))
    except subprocess.TimeoutExpired:
        raise SandboxError(
            f"Песочница: превышен таймаут ({int(timeout)} с).") from None
    except OSError as exc:
        raise SandboxError(f"Песочница не запустилась: {exc}") from None
    line = (completed.stdout or "").strip().splitlines()
    if not line:
        detail = (completed.stderr or "").strip().splitlines()
        raise SandboxError("Песочница не ответила: "
                           + (detail[-1] if detail else "нет вывода"))
    try:
        return json.loads(line[-1])
    except json.JSONDecodeError:
        raise SandboxError("Песочница вернула некорректный ответ.") from None


def describe_plugin(path: str | Path, *, timeout: float = DEFAULT_TIMEOUT,
                    memory_mb: int = DEFAULT_MEMORY_MB) -> tuple[dict, str]:
    """Inspect a plugin in the sandbox: (meta, error)."""
    try:
        answer = _worker({"op": "describe", "path": str(path)},
                         timeout=timeout, memory_mb=memory_mb)
    except SandboxError as exc:
        return {}, str(exc)
    if not answer.get("ok"):
        return {}, str(answer.get("error") or "неизвестная ошибка плагина")
    return dict(answer.get("meta") or {}), ""


def run_tool(path: str | Path, tool: str, args: dict,
             *, timeout: float = DEFAULT_TIMEOUT,
             memory_mb: int = DEFAULT_MEMORY_MB) -> dict:
    """Execute one tool handler inside the sandbox; returns its result."""
    try:
        answer = _worker({"op": "run", "path": str(path), "tool": str(tool),
                          "args": dict(args or {})},
                         timeout=timeout, memory_mb=memory_mb)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    if not answer.get("ok"):
        return {"ok": False, "error": str(answer.get("error")
                                          or "ошибка плагина")}
    result = answer.get("result")
    return result if isinstance(result, dict) else {"ok": True, "result": result}
