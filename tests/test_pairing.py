"""Tests for bracket auto-closing and match finding."""
from __future__ import annotations

from alterego_training_hub.pairing import (
    auto_close_decision,
    backspace_decision,
    bracket_for_cursor,
    find_matching_bracket,
)


def test_auto_close_pairs_and_skips():
    assert auto_close_decision("", 0, "(") == "pair"
    assert auto_close_decision("foo(", 4, "[") == "pair"
    assert auto_close_decision("x = (", 5, "{") == "pair"
    # Typing a closer over an existing closer just steps over it.
    assert auto_close_decision("()", 1, ")") == "skip"
    assert auto_close_decision("x", 1, ")") == "type"
    # Quotes after a word char stay plain (apostrophes in words).
    assert auto_close_decision("", 0, '"') == "pair"
    assert auto_close_decision("don", 3, "'") == "type"
    assert auto_close_decision("say ", 4, "'") == "pair"
    # Non-pair characters are plain typing.
    assert auto_close_decision("a", 1, "b") == "type"


def test_backspace_inside_empty_pair():
    assert backspace_decision("()", 1) == 2
    assert backspace_decision("[]", 1) == 2
    assert backspace_decision('""', 1) == 2
    assert backspace_decision("(x)", 2) == 1
    assert backspace_decision("a", 1) == 1
    assert backspace_decision("", 0) == 1


def test_find_matching_bracket_nested_and_backward():
    text = "def f(a, b=[1, 2]):\n    return (a)"
    open_def, close_def = text.index("("), text.index(")")
    assert find_matching_bracket(text, open_def) == close_def
    assert find_matching_bracket(text, close_def) == open_def
    open_ret, close_ret = text.rindex("("), text.rindex(")")
    assert find_matching_bracket(text, open_ret) == close_ret
    assert find_matching_bracket(text, close_ret) == open_ret
    nested = "([{}])"
    assert find_matching_bracket(nested, 0) == 5
    assert find_matching_bracket(nested, 1) == 4
    assert find_matching_bracket(nested, 4) == 1


def test_find_matching_bracket_mismatches_and_edges():
    assert find_matching_bracket("([)]", 0) is None  # interleaved → error
    assert find_matching_bracket("((", 0) is None    # unclosed
    assert find_matching_bracket("plain", 2) is None
    assert find_matching_bracket("(x)", 99) is None
    assert find_matching_bracket("(x)", -1) is None


def test_bracket_for_cursor_prefers_char_under_cursor():
    text = "a(b)c"
    assert bracket_for_cursor(text, 1) == 1
    assert bracket_for_cursor(text, 2) == 1  # just after the bracket
    assert bracket_for_cursor(text, 0) is None
