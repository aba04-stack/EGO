"""Syntax highlighting for the code editor (Tk text tags, no heavy parsers).

Small regex-based colouring for Python, data files (YAML/JSON) and a generic
fallback. Tag priorities: comments beat strings, strings beat keywords.
"""
from __future__ import annotations

import re

from .theme import SYNTAX

PYTHON_KEYWORDS = {
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
    "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
}
PYTHON_BUILTINS = {
    "self", "cls", "print", "len", "range", "int", "str", "float", "dict",
    "list", "set", "tuple", "bool", "bytes", "open", "isinstance", "super",
    "enumerate", "zip", "map", "filter", "sorted", "min", "max", "sum", "abs",
    "ValueError", "TypeError", "KeyError", "RuntimeError", "Exception", "None",
}

_COMMENT_RE = re.compile(r"#[^\n]*")
_STRING_RE = re.compile(
    r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`")
_WORD_RE = re.compile(r"[A-Za-z_]\w*")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_DEF_RE = re.compile(r"\b(?:def|class)\s+([A-Za-z_]\w*)")
_YAML_KEY_RE = re.compile(r"^(\s*[\w.\-/]+)(?=\s*:)", re.MULTILINE)

_TAG_ORDER = ("number", "keyword", "builtin", "defname", "key",
              "string", "comment")  # later tags win on overlap


def detect_language(path: str) -> str:
    lower = str(path).lower()
    if lower.endswith(".py") or lower.endswith(".pyw"):
        return "python"
    if lower.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg")):
        return "data"
    if lower.endswith((".md", ".txt", ".rst")):
        return "text"
    return "generic"


def configure_tags(widget) -> None:
    """Register highlight tags on a text widget (idempotent)."""
    for name in _TAG_ORDER:
        color = SYNTAX.get("key" if name == "key" else name, SYNTAX["comment"])
        try:
            widget.tag_configure(name, foreground=color)
        except Exception:
            pass


def _inside(spans: list[tuple[int, int]], position: int) -> bool:
    return any(start <= position < end for start, end in spans)


def highlight(widget, language: str) -> int:
    """Colourise the widget buffer; returns the number of tagged regions."""
    try:
        text = widget.get("1.0", "end-1c")
    except Exception:
        return 0
    for tag in _TAG_ORDER:
        try:
            widget.tag_remove(tag, "1.0", "end")
        except Exception:
            pass

    count = 0

    def paint(tag: str, start: int, end: int) -> None:
        nonlocal count
        try:
            widget.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")
            count += 1
        except Exception:
            pass

    comments = [(m.start(), m.end()) for m in _COMMENT_RE.finditer(text)] \
        if language != "text" else []
    strings = [(m.start(), m.end()) for m in _STRING_RE.finditer(text)
               if not _inside(comments, m.start())]

    def in_code(position: int) -> bool:
        return not _inside(comments, position) and not _inside(strings, position)

    if language in {"python", "generic"}:
        for match in _WORD_RE.finditer(text):
            if not in_code(match.start()):
                continue
            word = match.group(0)
            if word in PYTHON_KEYWORDS:
                paint("keyword", match.start(), match.end())
            elif word in PYTHON_BUILTINS:
                paint("builtin", match.start(), match.end())
        for match in _DEF_RE.finditer(text):
            if not _inside(comments, match.start(1)):
                paint("defname", match.start(1), match.end(1))
    if language == "data":
        for match in _YAML_KEY_RE.finditer(text):
            paint("key", match.start(1), match.end(1))

    for match in _NUMBER_RE.finditer(text):
        if in_code(match.start()):
            paint("number", match.start(), match.end())
    for start, end in strings:
        paint("string", start, end)
    for start, end in comments:
        paint("comment", start, end)
    return count
