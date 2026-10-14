"""Tests for the editor find/replace helpers."""
from __future__ import annotations

from alterego_training_hub.finding import (
    iter_matches,
    next_match_index,
    replace_all,
    replace_span,
)


def test_iter_matches_case_and_word():
    text = "Beta beta BETA alphabet"
    assert iter_matches(text, "beta") == [(0, 4), (5, 9), (10, 14)]
    assert iter_matches(text, "beta", case_sensitive=True) == [(5, 9)]
    assert iter_matches(text, "beta", whole_word=True, case_sensitive=True) == [(5, 9)]
    assert iter_matches("beta1 beta", "beta", whole_word=True) == [(6, 10)]
    assert iter_matches("beta1", "beta", whole_word=True) == []
    assert iter_matches(text, "") == []


def test_next_match_index_wraps():
    matches = [(0, 3), (10, 13), (20, 23)]
    assert next_match_index(matches, 0, 1) == 0
    assert next_match_index(matches, 4, 1) == 1
    assert next_match_index(matches, 100, 1) == 0  # wrap forward
    assert next_match_index(matches, 14, -1) == 1
    assert next_match_index(matches, 0, -1) == 2  # wrap backward
    assert next_match_index([], 0, 1) is None


def test_replace_all_and_span():
    text = "a-x b-x"
    new_text, count = replace_all(text, "-x", "+y")
    assert new_text == "a+y b+y" and count == 2

    same, zero = replace_all(text, "zz", "q")
    assert same == text and zero == 0

    assert replace_span(text, (0, 3), "Q") == "Q b-x"
