"""Sandbox worker: executes plugin code under restricted builtins.

Invoked as ``python -m alterego_training_hub.plugin_worker`` with a JSON
request on stdin; prints one JSON answer on stdout. See ``plugin_sandbox``
for the trust model. ``--memory-mb`` caps the address space on POSIX.
"""
from __future__ import annotations

import argparse
import builtins
import importlib
import json
import sys
import traceback
from pathlib import Path

ALLOWED_IMPORTS = frozenset({
    "json", "math", "re", "datetime", "time", "random", "string",
    "collections", "itertools", "functools", "typing", "dataclasses",
    "textwrap", "uuid", "decimal", "statistics", "hashlib", "base64",
})

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "bytes", "callable", "chr", "dict",
    "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "getattr", "hasattr", "hash", "hex", "id", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "oct", "ord", "pow", "print", "range", "repr", "reversed", "round",
    "set", "slice", "sorted", "str", "sum", "tuple", "zip",
    "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError",
    "ArithmeticError", "Exception", "RuntimeError", "ZeroDivisionError",
    "NotImplementedError", "StopIteration", "True", "False", "None",
)


class SandboxViolation(RuntimeError):
    """A plugin tried to escape the sandbox."""


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    root = str(name).split(".")[0]
    if root not in ALLOWED_IMPORTS:
        raise SandboxViolation(
            f"import «{root}» запрещён в песочнице — "
            "отметьте плагин как доверенный")
    return importlib.__import__(name, globals, locals, fromlist, level)


def _restricted_builtins() -> dict:
    table = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES
             if hasattr(builtins, name)}
    table["__import__"] = _safe_import
    return table


def _load_payload(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    namespace: dict = {
        "__builtins__": _restricted_builtins(),
        "__name__": f"alterego_sandbox_{path.stem}",
        "__file__": str(path),
    }
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102
    payload = namespace.get("PLUGIN")
    if not isinstance(payload, dict):
        raise SandboxViolation("в модуле нет словаря PLUGIN")
    return payload


def _describe(path: Path) -> dict:
    from alterego_training_hub.plugin_sandbox import build_meta

    payload = _load_payload(path)
    meta, error = build_meta(payload, path)
    if error:
        return {"ok": False, "error": error}
    return {"ok": True, "meta": meta}


def _run(path: Path, tool: str, args: dict) -> dict:
    payload = _load_payload(path)
    tools = payload.get("tools") or {}
    spec = tools.get(tool)
    if not isinstance(spec, dict):
        return {"ok": False, "error": f"нет инструмента «{tool}»"}
    handler = spec.get("handler")
    if not callable(handler):
        return {"ok": False, "error": f"handler инструмента «{tool}» не вызываем"}
    try:
        result = handler(args)
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        return {"ok": False,
                "error": f"{type(exc).__name__}: {exc}"}
    try:
        json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"ok": False,
                "error": "результат инструмента не сериализуем в JSON"}
    return {"ok": True, "result": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alterego_plugin_worker")
    parser.add_argument("--memory-mb", type=int, default=256)
    options = parser.parse_args(argv)
    if options.memory_mb > 0:
        try:
            import resource

            cap = int(options.memory_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        except (ImportError, OSError, ValueError):
            pass  # non-POSIX or hard limit above our soft one
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error": "некорректный запрос"}))
        return 0
    path = Path(str(request.get("path") or ""))
    answer: dict
    try:
        if request.get("op") == "describe":
            answer = _describe(path)
        elif request.get("op") == "run":
            answer = _run(path, str(request.get("tool") or ""),
                          dict(request.get("args") or {}))
        else:
            answer = {"ok": False, "error": "неизвестная операция"}
    except SandboxViolation as exc:
        answer = {"ok": False, "error": f"Песочница: {exc}"}
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        answer = {"ok": False,
                  "error": f"{type(exc).__name__}: {exc}",
                  "trace": traceback.format_exc(limit=3)}
    print(json.dumps(answer, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
