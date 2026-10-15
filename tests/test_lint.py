"""Tests for the built-in pure Python linter."""
from __future__ import annotations

from alterego_training_hub.lint import check_python, check_source, check_text


def test_syntax_error_reported_with_line():
    text = "def broken(:\n    pass\n"
    problems = check_python(text, path="a.py")
    assert problems[0]["severity"] == "error"
    assert problems[0]["line"] == 1
    assert "Синтаксическая ошибка" in problems[0]["message"]
    assert problems[0]["path"] == "a.py"


def test_clean_python_has_no_problems():
    text = "def add(a, b):\n    return a + b\n"
    assert check_python(text, path="ok.py") == []


def test_style_warnings():
    text = (
        "x = 1  \n"                    # trailing spaces (line 1)
        "def f():\n"                   # line 2
        "\treturn 2\n"                 # tab indent (line 3)
        "y = '" + "z" * 120 + "'\n"    # long line (line 4)
    )
    problems = check_python(text, path="style.py")
    messages = [p["message"] for p in problems]
    assert any("Лишние пробелы" in m for m in messages)
    assert any("Табуляция" in m for m in messages)
    assert any("Длинная строка" in m for m in messages)
    assert all(p["severity"] == "warn" for p in problems)
    assert [p["line"] for p in problems] == [1, 3, 4]


def test_check_text_and_dispatch():
    assert len(check_text("a  \nb\n", path="n.txt")) == 1
    assert check_text("clean\n", path="n.txt") == []
    assert check_source("x = 1  \n", path="a.py",
                        language="python") == [
        {"severity": "warn", "message": "Лишние пробелы в конце строки",
         "path": "a.py", "line": 1}]
    assert check_source("ok\n", path="a.txt", language="text") == []
