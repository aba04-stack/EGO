"""Pure helpers for bracket auto-closing and match highlighting."""
from __future__ import annotations

import re

PAIRS: dict[str, str] = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS: dict[str, str] = {closer: opener for opener, closer in PAIRS.items()}
_WORD_CHAR = re.compile(r"\w")


def auto_close_decision(line: str, col: int, char: str) -> str:
    """Decide how to handle typing ``char`` at column ``col`` of ``line``.

    Returns ``"pair"`` (insert both chars, cursor between them),
    ``"skip"`` (step over the existing closer), or ``"type"`` (plain insert).
    Quotes after a word character stay plain so `don't` works.
    """
    if char in PAIRS and char in CLOSERS:
        # Quotes play both roles: step over an existing quote, stay plain
        # after a word char (`don't`), otherwise auto-close.
        if line[col:col + 1] == char:
            return "skip"
        if col > 0 and _WORD_CHAR.match(line[col - 1]):
            return "type"
        return "pair"
    if char in CLOSERS:
        return "skip" if line[col:col + 1] == char else "type"
    if char in PAIRS:
        return "pair"
    return "type"


def backspace_decision(line: str, col: int) -> int:
    """How many characters Backspace deletes at ``col``.

    Returns 2 when the cursor sits inside an empty pair ``(``|``)``.
    """
    if col >= 1:
        opener = line[col - 1]
        if opener in PAIRS and line[col:col + 1] == PAIRS[opener]:
            return 2
    return 1


def bracket_for_cursor(text: str, cursor: int) -> int | None:
    """Offset of the bracket the cursor touches (at or just before)."""
    for candidate in (cursor, cursor - 1):
        if 0 <= candidate < len(text) and (
            text[candidate] in PAIRS or text[candidate] in CLOSERS
        ):
            return candidate
    return None


def find_matching_bracket(text: str, index: int) -> int | None:
    """Offset of the bracket matching the one at ``index``, or None.

    Uses a bracket stack (handles nested mixed pairs like ``([{}])``);
    a mismatched region yields None, like editors highlighting an error.
    """
    if not 0 <= index < len(text):
        return None
    ch = text[index]
    if ch in PAIRS:
        stack = [ch]
        for i in range(index + 1, len(text)):
            c = text[i]
            if c in PAIRS:
                stack.append(c)
            elif c in CLOSERS:
                if not stack or CLOSERS[c] != stack[-1]:
                    return None
                stack.pop()
                if not stack:
                    return i
        return None
    if ch in CLOSERS:
        stack = [ch]
        for i in range(index - 1, -1, -1):
            c = text[i]
            if c in CLOSERS:
                stack.append(c)
            elif c in PAIRS:
                if not stack or PAIRS[c] != stack[-1]:
                    return None
                stack.pop()
                if not stack:
                    return i
        return None
    return None
