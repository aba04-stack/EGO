"""Tests for the minimap sampling helpers."""
from __future__ import annotations

from alterego_training_hub.minimap import line_kind, minimap_bars


def test_line_kind_categories():
    assert line_kind("") == "blank"
    assert line_kind("    ") == "blank"
    assert line_kind("# note") == "comment"
    assert line_kind("def train():") == "def"
    assert line_kind("class Model:") == "def"
    assert line_kind("async def run():") == "def"
    assert line_kind("if ready:") == "head"
    assert line_kind("from x import y") == "head"
    assert line_kind("    loss = 0") == "code"


def test_minimap_bars_fields_and_caps():
    text = "def f():\n" + " " * 80 + "x = 1\n" + "y = '" + "z" * 100 + "'\n"
    bars = minimap_bars(text)
    assert len(bars) == 3
    assert bars[0]["kind"] == "def" and bars[0]["line"] == 1
    assert bars[1]["indent"] == 40          # capped
    assert bars[2]["width"] == 60           # capped


def test_minimap_bars_sampling_long_file():
    text = "\n".join(f"x = {i}" for i in range(500))
    bars = minimap_bars(text, limit=100)
    assert len(bars) == 100
    assert bars[0]["line"] == 1
    assert bars[-1]["line"] > 400           # last sample near the end
    assert minimap_bars("") == []
