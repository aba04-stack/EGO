"""Tests for training-log problem parsing and the problems panel wiring."""
from __future__ import annotations

from alterego_training_hub.problems import parse_problems

SAMPLE_LOG = """\
2026-10-13 14:40:01 INFO start training
Traceback (most recent call last):
  File "train.py", line 42, in <module>
    raise ValueError("bad batch")
ValueError: bad batch
FAILED tests/test_loss.py::test_val_loss_finite
2026-10-13 14:41:00 WARNING val_loss: 1.22
"""


def test_parse_problems_extracts_file_and_line():
    problems = parse_problems(SAMPLE_LOG)
    assert problems

    with_line = [p for p in problems if p["path"] == "train.py"]
    assert with_line and with_line[0]["line"] == 42
    assert with_line[0]["severity"] == "error"

    failed = [p for p in problems if p["path"] == "tests/test_loss.py"]
    assert failed and "test_val_loss_finite" in failed[0]["message"]

    messages = [p["message"] for p in problems]
    assert any("ValueError" in m for m in messages)
    assert all(len(p) == 4 for p in problems)  # severity/message/path/line


def test_parse_problems_limits_and_dedupes():
    log = "".join(f"ERROR: boom {i}\n" for i in range(50))
    problems = parse_problems(log, limit=10)
    assert len(problems) == 10
    # duplicates collapse
    assert len(parse_problems("ERROR: boom\nERROR: boom\n")) == 1


def test_parse_problems_clean_log():
    assert parse_problems("epoch 1 loss 0.5\nepoch 2 loss 0.4\n") == []
