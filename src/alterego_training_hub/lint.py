"""Pure Python/text checks: syntax and quick style (no subprocess)."""
from __future__ import annotations

import re

MAX_LINE_LENGTH = 100
MAX_PROBLEMS = 200
_TAB_INDENT_RE = re.compile(r"^ *\t")


def _problem(severity: str, message: str, path: str, line: int) -> dict:
    return {"severity": severity, "message": message[:200], "path": str(path),
            "line": int(line or 0)}


def check_python(text: str, *, path: str = "file.py") -> list[dict]:
    """Syntax errors (via ``compile``) plus quick style warnings."""
    problems: list[dict] = []

    def add(severity: str, message: str, line: int):
        if len(problems) < MAX_PROBLEMS:
            problems.append(_problem(severity, message, path, line))

    try:
        compile(text, str(path), "exec")
    except SyntaxError as exc:
        add("error", f"Синтаксическая ошибка: {exc.msg}", exc.lineno or 0)
    except ValueError as exc:
        add("error", f"Недопустимый исходный код: {exc}", 0)

    for number, line in enumerate(text.splitlines(), 1):
        if line != line.rstrip():
            add("warn", "Лишние пробелы в конце строки", number)
        if _TAB_INDENT_RE.match(line):
            add("warn", "Табуляция в отступе — используйте 4 пробела", number)
        if len(line) > MAX_LINE_LENGTH:
            add("warn", f"Длинная строка: {len(line)} символов "
                        f"(максимум {MAX_LINE_LENGTH})", number)
    return problems


def check_text(text: str, *, path: str = "file.txt") -> list[dict]:
    """Whitespace-only checks for non-Python files."""
    problems: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line != line.rstrip() and len(problems) < MAX_PROBLEMS:
            problems.append(_problem("warn", "Лишние пробелы в конце строки",
                                     path, number))
    return problems


def check_source(text: str, *, path: str, language: str) -> list[dict]:
    """Dispatch checks by the editor's detected language."""
    if language == "python":
        return check_python(text, path=path)
    return check_text(text, path=path)
