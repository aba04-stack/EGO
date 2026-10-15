"""Find/replace logic for the editor (no Tk — testable helpers)."""
from __future__ import annotations


def iter_matches(text: str, query: str, *, case_sensitive: bool = False,
                 whole_word: bool = False) -> list[tuple[int, int]]:
    """All non-overlapping matches as (start, end) offsets into ``text``."""
    if not query:
        return []
    haystack = text if case_sensitive else text.lower()
    needle = query if case_sensitive else query.lower()
    matches: list[tuple[int, int]] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        end = index + len(needle)
        if whole_word and not _is_whole(text, index, end):
            start = index + 1
            continue
        matches.append((index, end))
        start = end
    return matches


def _is_whole(text: str, start: int, end: int) -> bool:
    before_ok = start == 0 or not (text[start - 1].isalnum() or text[start - 1] == "_")
    after_ok = end >= len(text) or not (text[end].isalnum() or text[end] == "_")
    return before_ok and after_ok


def next_match_index(matches: list[tuple[int, int]], cursor: int,
                     direction: int = 1) -> int | None:
    """Index of the next match to jump to from ``cursor`` (wraps around)."""
    if not matches:
        return None
    if direction >= 0:
        for position, (start, _end) in enumerate(matches):
            if start >= cursor:
                return position
        return 0
    for position in range(len(matches) - 1, -1, -1):
        if matches[position][0] < cursor:
            return position
    return len(matches) - 1


def replace_all(text: str, query: str, replacement: str, *,
                case_sensitive: bool = False, whole_word: bool = False
                ) -> tuple[str, int]:
    """Replace every match; returns (new_text, replace_count)."""
    matches = iter_matches(text, query, case_sensitive=case_sensitive,
                           whole_word=whole_word)
    if not matches:
        return text, 0
    pieces: list[str] = []
    position = 0
    for start, end in matches:
        pieces.append(text[position:start])
        pieces.append(replacement)
        position = end
    pieces.append(text[position:])
    return "".join(pieces), len(matches)


def replace_span(text: str, span: tuple[int, int], replacement: str) -> str:
    return text[:span[0]] + replacement + text[span[1]:]
