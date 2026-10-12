"""Workspace-scoped tools the AI mentor can invoke to inspect and fix code.

Every file operation is confined to a single workspace folder chosen by the
user. Command execution never uses a shell and always runs inside that folder.
Mutating tools are marked so the UI can require explicit confirmation.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

READONLY_TOOLS: frozenset[str] = frozenset({"list_files", "read_file", "search_files"})

# Human-readable descriptions shown in confirmation dialogs (Russian UI).
TOOL_DESCRIPTIONS_RU: dict[str, str] = {
    "list_files": "Показать файлы и папки",
    "read_file": "Прочитать файл",
    "search_files": "Поиск по содержимому файлов",
    "write_file": "Записать/создать файл",
    "replace_in_file": "Заменить текст в файле",
    "run_command": "Выполнить команду",
}

MAX_FILE_READ_BYTES = 200_000
MAX_TOOL_OUTPUT_CHARS = 20_000
MAX_LIST_ENTRIES = 400
MAX_SEARCH_MATCHES = 200
DEFAULT_COMMAND_TIMEOUT = 120.0

_IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}


class ToolError(RuntimeError):
    """Tool rejected input or failed in a way safe to show the user."""


# OpenAI-compatible function-calling schemas advertised to the mentor.
WORKSPACE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Список файлов и папок внутри рабочей папки проекта.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Относительный путь подпапки; по умолчанию корень"},
                    "recursive": {"type": "boolean", "description": "Рекурсивный обход", "default": False},
                    "max_entries": {"type": "integer", "description": "Максимум записей", "default": 200},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать текстовый файл из рабочей папки.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Относительный путь файла"},
                    "max_bytes": {"type": "integer", "description": "Максимум байт", "default": 60000},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Поиск регулярного выражения по текстовым файлам рабочей папки.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Регулярное выражение (Python re)"},
                    "glob": {"type": "string", "description": "Например '*.py'; по умолчанию '**/*'"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Создать или полностью перезаписать файл в рабочей папке.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Относительный путь файла"},
                    "content": {"type": "string", "description": "Новое полное содержимое файла"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Заменить точный фрагмент текста в файле (одно или несколько вхождений).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Относительный путь файла"},
                    "find": {"type": "string", "description": "Точный текст для поиска"},
                    "replace": {"type": "string", "description": "Текст замены"},
                    "count": {"type": "integer", "description": "Сколько вхождений заменить; 0 = все", "default": 0},
                },
                "required": ["path", "find", "replace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Выполнить команду (без shell) внутри рабочей папки и вернуть вывод.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Команда с аргументами, например 'python -m pytest -q'"},
                    "timeout_seconds": {"type": "integer", "description": "Таймаут 1–600 секунд", "default": 120},
                },
                "required": ["command"],
            },
        },
    },
]

TOOL_NAMES: frozenset[str] = frozenset(
    schema["function"]["name"] for schema in WORKSPACE_TOOL_SCHEMAS
)


def _clip(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[вывод обрезан, всего {len(text)} символов]"


class WorkspaceTools:
    """File and command tools confined to one workspace folder."""

    def __init__(self, root: str | Path, backup_dir: str | Path | None = None):
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ToolError(f"Рабочая папка не найдена: {root_path}")
        self.root = root_path
        self.backup_dir = Path(backup_dir) if backup_dir else None

    # -- path safety -----------------------------------------------------
    def _resolve(self, relative: str, *, must_exist: bool = False) -> Path:
        rel = str(relative or "").strip()
        if "\x00" in rel:
            raise ToolError("Недопустимый путь.")
        candidate = (self.root / rel).resolve() if rel else self.root
        if candidate != self.root and not candidate.is_relative_to(self.root):
            raise ToolError("Доступ разрешён только внутри рабочей папки.")
        if must_exist and not candidate.exists():
            raise ToolError(f"Не найдено: {rel or '.'}")
        return candidate

    def _backup(self, target: Path) -> str | None:
        """Copy the pre-edit file into the backup folder; returns backup path."""
        if self.backup_dir is None or not target.is_file():
            return None
        import shutil
        from datetime import datetime

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        try:
            rel = target.relative_to(self.root)
        except ValueError:
            return None
        destination = self.backup_dir / stamp / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        return str(destination)

    # -- dispatch --------------------------------------------------------
    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        handler: Callable[..., dict[str, Any]] | None = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "search_files": self.search_files,
            "write_file": self.write_file,
            "replace_in_file": self.replace_in_file,
            "run_command": self.run_command,
        }.get(str(name))
        if handler is None:
            return {"ok": False, "error": f"Неизвестный инструмент: {name}"}
        import inspect

        try:
            inspect.signature(handler).bind(**args)
        except TypeError:
            return {"ok": False, "error": f"Неверные аргументы инструмента {name}: {args}"}
        try:
            return handler(**args)
        except ToolError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - tool boundary must not crash the agent
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def is_readonly(name: str) -> bool:
        return name in READONLY_TOOLS

    @staticmethod
    def describe(name: str, arguments: dict[str, Any] | None = None) -> str:
        args = arguments or {}
        base = TOOL_DESCRIPTIONS_RU.get(name, name)
        if name == "read_file":
            return f"{base}: {args.get('path', '')}"
        if name == "write_file":
            return f"{base}: {args.get('path', '')} ({len(str(args.get('content', '')))} символов)"
        if name == "replace_in_file":
            return f"{base}: {args.get('path', '')}"
        if name == "run_command":
            return f"{base}: {args.get('command', '')}"
        if name == "search_files":
            return f"{base}: {args.get('pattern', '')}"
        return base

    # -- tools -----------------------------------------------------------
    def list_files(self, path: str = "", recursive: bool = False,
                   max_entries: int = 200) -> dict[str, Any]:
        base = self._resolve(path, must_exist=True)
        if not base.is_dir():
            raise ToolError(f"Это не папка: {path or '.'}")
        limit = max(1, min(int(max_entries), MAX_LIST_ENTRIES))
        entries: list[str] = []
        if recursive:
            for item in sorted(base.rglob("*")):
                if any(part in _IGNORED_DIRS for part in item.relative_to(base).parts):
                    continue
                suffix = "/" if item.is_dir() else ""
                entries.append(str(item.relative_to(self.root)) + suffix)
                if len(entries) >= limit:
                    break
        else:
            for item in sorted(base.iterdir()):
                suffix = "/" if item.is_dir() else ""
                entries.append(item.name + suffix)
                if len(entries) >= limit:
                    break
        return {"ok": True, "root": str(self.root), "entries": entries, "count": len(entries)}

    def read_file(self, path: str, max_bytes: int = 60_000) -> dict[str, Any]:
        target = self._resolve(path, must_exist=True)
        if not target.is_file():
            raise ToolError(f"Это не файл: {path}")
        limit = max(1, min(int(max_bytes), MAX_FILE_READ_BYTES))
        raw = target.read_bytes()[: limit + 1]
        truncated = len(raw) > limit
        text = raw[:limit].decode("utf-8", errors="replace")
        return {"ok": True, "path": str(target.relative_to(self.root)), "content": text,
                "truncated": truncated}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ToolError("Содержимое должно быть текстом.")
        target = self._resolve(path)
        if target == self.root:
            raise ToolError("Укажите путь файла внутри рабочей папки.")
        created = not target.exists()
        backup = self._backup(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        result: dict[str, Any] = {
            "ok": True,
            "path": str(target.relative_to(self.root)),
            "created": created,
            "bytes": len(content.encode("utf-8")),
        }
        if backup:
            result["backup"] = backup
        return result

    def replace_in_file(self, path: str, find: str, replace: str, count: int = 0) -> dict[str, Any]:
        if not isinstance(find, str) or not find:
            raise ToolError("Текст для поиска не должен быть пустым.")
        if not isinstance(replace, str):
            raise ToolError("Текст замены должен быть строкой.")
        target = self._resolve(path, must_exist=True)
        if not target.is_file():
            raise ToolError(f"Это не файл: {path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        occurrences = text.count(find)
        if occurrences == 0:
            raise ToolError("Искомый фрагмент не найден в файле.")
        limit = occurrences if int(count) <= 0 else min(int(count), occurrences)
        backup = self._backup(target)
        new_text = text.replace(find, replace, limit)
        target.write_text(new_text, encoding="utf-8")
        result: dict[str, Any] = {
            "ok": True,
            "path": str(target.relative_to(self.root)),
            "replaced": limit,
            "remaining": occurrences - limit,
        }
        if backup:
            result["backup"] = backup
        return result

    def search_files(self, pattern: str, glob: str = "**/*") -> dict[str, Any]:
        try:
            regex = re.compile(str(pattern))
        except re.error as exc:
            raise ToolError(f"Некорректное регулярное выражение: {exc}") from None
        base_glob = str(glob or "**/*").strip() or "**/*"
        # A bare "*.py" pattern should search recursively, as users expect.
        if "/" not in base_glob and "\\" not in base_glob:
            base_glob = "**/" + base_glob
        matches: list[str] = []
        scanned = 0
        for item in sorted(self.root.glob(base_glob)):
            if not item.is_file():
                continue
            rel_parts = item.relative_to(self.root).parts
            if any(part in _IGNORED_DIRS for part in rel_parts):
                continue
            if item.stat().st_size > 1_000_000:
                continue
            scanned += 1
            try:
                text = item.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{item.relative_to(self.root)}:{line_no}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        return {"ok": True, "matches": matches, "scanned_files": scanned,
                                "truncated": True}
        return {"ok": True, "matches": matches, "scanned_files": scanned, "truncated": False}

    def run_command(self, command: str, timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT) -> dict[str, Any]:
        if not isinstance(command, str) or not command.strip():
            raise ToolError("Команда не должна быть пустой.")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ToolError(f"Не удалось разобрать команду: {exc}") from None
        if not argv:
            raise ToolError("Команда не должна быть пустой.")
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            raise ToolError("Таймаут должен быть числом.") from None
        if not 1 <= timeout <= 600:
            raise ToolError("Таймаут должен быть от 1 до 600 секунд.")
        try:
            result = subprocess.run(
                argv,
                cwd=str(self.root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            raise ToolError(f"Команда не найдена: {argv[0]}") from None
        except subprocess.TimeoutExpired:
            raise ToolError(f"Команда не завершилась за {timeout:.0f} сек.") from None
        output = _clip(result.stdout or "")
        return {"ok": True, "command": command, "returncode": result.returncode, "output": output}

    def snapshot_json(self) -> str:
        """Short JSON summary of the workspace for prompt context."""
        info = {
            "root": str(self.root),
            "entries": self.list_files(max_entries=50)["entries"],
        }
        return json.dumps(info, ensure_ascii=False)
