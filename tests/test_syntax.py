"""Tests for syntax highlighting and editor completion candidates."""
from __future__ import annotations

from alterego_training_hub.completion import collect_candidates, current_word
from alterego_training_hub.syntax import configure_tags, detect_language, highlight


class StubText:
    """Minimal text-widget stand-in that records tag operations."""

    def __init__(self, value: str):
        self._value = value
        self.tags: list[tuple[str, str, str]] = []

    def get(self, _start, _end):
        return self._value

    def tag_configure(self, *args, **kwargs):
        pass

    def tag_remove(self, *args):
        pass

    def tag_add(self, tag, start, end):
        self.tags.append((tag, start, end))


def test_detect_language():
    assert detect_language("src/train.py") == "python"
    assert detect_language("config.YML".lower()) == "data"
    assert detect_language("README.md") == "text"
    assert detect_language("script.sh") == "generic"


def test_highlight_python_tags():
    widget = StubText(
        "# comment here\n"
        "def train(model):\n"
        '    name = "value"  # trailing\n'
        "    return model + 1\n"
    )
    configure_tags(widget)
    count = highlight(widget, "python")
    assert count > 0

    painted = {}
    for tag, start, end in widget.tags:
        painted.setdefault(tag, []).append(widget._value[
            int(start.split("+")[1][:-1]):int(end.split("+")[1][:-1])])

    assert "def" in painted.get("keyword", [])
    assert "train" in painted.get("defname", [])
    assert '"value"' in painted.get("string", [])
    assert "1" in painted.get("number", [])
    comments = painted.get("comment", [])
    assert any(text.startswith("#") for text in comments)
    # keyword inside a string is not painted as keyword
    assert '"value"' not in painted.get("keyword", [])


def test_highlight_data_keys_and_text_skip():
    widget = StubText("model: gpt\nsteps: 10\n")
    highlight(widget, "data")
    painted = [tag for tag, _s, _e in widget.tags]
    assert "key" in painted and "number" in painted

    widget2 = StubText("just prose\n")
    assert highlight(widget2, "text") == 0


def test_completion_candidates():
    text = "import torch\n\ndef train_model():\n    model = train_model()\n"
    prefix, start = current_word("def tra", 7)
    assert prefix == "tra" and start == 4

    words = collect_candidates(text, "tra")
    assert "train_model" in words and "torch" not in words
    assert collect_candidates(text, "t") == []  # prefix too short
    # vocabulary includes Python keywords
    assert "return" in collect_candidates(text, "ret")
