"""Tests for the built-in pure formatter."""
from __future__ import annotations

from alterego_training_hub.formatter import format_source


def test_clean_text_untouched_with_zero_fixes():
    text = "def f():\n    return 1\n"
    assert format_source(text) == (text, 0)


def test_trailing_whitespace_and_final_newline():
    new_text, fixes = format_source("x = 1  \ny = 2")
    assert new_text == "x = 1\ny = 2\n"
    assert fixes == 2  # one trailing-space line + missing final newline


def test_line_endings_normalized():
    new_text, fixes = format_source("a\r\nb\rc\n")
    assert new_text == "a\nb\nc\n"
    assert fixes == 2


def test_blank_lines_capped_and_trimmed():
    new_text, fixes = format_source("\n\n\na\n\n\n\n\nb\n\n\n")
    assert new_text == "a\n\n\nb\n"
    # splitlines: 3 leading + 4 middle (2 kept, 2 extra) + 2 trailing blanks
    assert fixes == 7


def test_empty_and_whitespace_only():
    assert format_source("") == ("", 0)
    new_text, fixes = format_source("  \n\n")
    assert new_text == ""
    assert fixes == 3
