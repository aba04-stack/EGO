"""Editor completion vocabulary (no Tk — used by the popup and tests)."""
from __future__ import annotations

import re

from .syntax import PYTHON_BUILTINS, PYTHON_KEYWORDS

_WORD_RE = re.compile(r"[A-Za-z_]\w*")
_MIN_PREFIX = 2
_MAX_CANDIDATES = 10


def current_word(text: str, cursor: int) -> tuple[str, int]:
    """Word prefix to the left of the cursor: returns (prefix, start_index)."""
    start = cursor
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    return text[start:cursor], start


def _count_chars(widget, index) -> int:
    try:
        result = widget.count("1.0", index, "chars")
    except Exception:  # noqa: BLE001 - fake widgets
        return 0
    if isinstance(result, (tuple, list)):
        result = result[0] if result else 0
    try:
        return int(result or 0)
    except (TypeError, ValueError):
        return 0


def collect_candidates(text: str, prefix: str, *, limit: int = _MAX_CANDIDATES) -> list[str]:
    """Words from the buffer + Python vocabulary matching the prefix."""
    if len(prefix) < _MIN_PREFIX:
        return []
    vocabulary = set(_WORD_RE.findall(text))
    vocabulary |= PYTHON_KEYWORDS | PYTHON_BUILTINS
    lowered = prefix.lower()
    matches = sorted(
        (word for word in vocabulary
         if word.lower().startswith(lowered) and word != prefix),
        key=lambda word: (len(word), word.lower()),
    )
    return matches[:limit]
