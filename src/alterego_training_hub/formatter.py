"""Pure source normalization: the built-in safe formatter (no subprocess)."""
from __future__ import annotations

_MAX_BLANK_LINES = 2


def format_source(text: str) -> tuple[str, int]:
    """Normalize source safely and return ``(new_text, fix_count)``.

    Rules (each fix is counted once per affected line):

    * CRLF / CR line endings become LF;
    * trailing whitespace on lines is removed;
    * runs of blank lines are capped at two, leading blanks are dropped;
    * trailing blank lines are dropped;
    * the file ends with exactly one newline (empty files stay empty).
    """
    fixes = 0
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized != text:
        fixes += text.count("\r")

    out: list[str] = []
    pending: list[str] = []  # blank lines waiting to be flushed
    for line in normalized.splitlines():
        stripped = line.rstrip()
        if stripped != line:
            fixes += 1
        if not stripped:
            pending.append(line)
            continue
        if not out:
            # Leading blank lines are dropped entirely.
            fixes += len(pending)
        else:
            fixes += max(0, len(pending) - _MAX_BLANK_LINES)
            out.extend([""] * min(len(pending), _MAX_BLANK_LINES))
        pending = []
        out.append(stripped)
    # Trailing blank lines are dropped entirely.
    fixes += len(pending)

    if not out:
        return "", fixes

    if normalized and not normalized.endswith("\n"):
        fixes += 1
    return "\n".join(out) + "\n", fixes
