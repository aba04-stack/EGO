"""Pure helpers to build a text minimap: one bar per sampled source line."""
from __future__ import annotations

import re

MAX_BARS = 120
MAX_INDENT = 40
MAX_WIDTH = 60

_DEF_RE = re.compile(r"^(async\s+def|def|class)\s+")
_KEYWORD_START_RE = re.compile(
    r"^(if|elif|else|for|while|try|except|finally|with|return|raise|import|"
    r"from|@)\b")


def line_kind(line: str) -> str:
    """Visual category of a line: blank / comment / def / head / code."""
    stripped = line.strip()
    if not stripped:
        return "blank"
    if stripped.startswith("#"):
        return "comment"
    if _DEF_RE.match(stripped):
        return "def"
    if _KEYWORD_START_RE.match(stripped):
        return "head"
    return "code"


def minimap_bars(text: str, *, limit: int = MAX_BARS) -> list[dict]:
    """Sample ``text`` into bars ``{indent, width, kind, line}``.

    ``line`` is the 1-based source line the bar stands for. When the file
    is longer than ``limit``, every n-th line is sampled.
    """
    lines = text.splitlines()
    if not lines:
        return []
    step = max(1, (len(lines) + limit - 1) // limit)
    bars: list[dict] = []
    for index in range(0, len(lines), step):
        if len(bars) >= limit:
            break
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        bars.append({
            "indent": min(indent, MAX_INDENT),
            "width": min(len(stripped), MAX_WIDTH),
            "kind": line_kind(line),
            "line": index + 1,
        })
    return bars
