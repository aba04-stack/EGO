"""Tests for the pure Git status/diff parsing helpers."""
from __future__ import annotations

from alterego_training_hub.vcs import (
    classify_diff_lines,
    parse_numstat,
    parse_porcelain,
    stat_totals,
)


def test_parse_porcelain_statuses():
    text = (
        " M src/app.py\n"
        "A  new.txt\n"
        "MM both.txt\n"
        "?? untracked.md\n"
        "D  gone.py\n"
        "R  old.py -> new.py\n"
    )
    rows = parse_porcelain(text)
    by_path = {row["path"]: row for row in rows}
    assert by_path["src/app.py"]["unstaged"] is True
    assert by_path["src/app.py"]["staged"] is False
    assert by_path["src/app.py"]["label"] == "изменён"
    assert by_path["new.txt"]["staged"] is True
    assert by_path["new.txt"]["label"] == "добавлен"
    assert by_path["both.txt"]["staged"] and by_path["both.txt"]["unstaged"]
    assert by_path["untracked.md"]["label"] == "не под индексом"
    assert by_path["untracked.md"]["staged"] is False
    assert by_path["gone.py"]["label"] == "удалён"
    assert by_path["new.py"]["original"] == "old.py"
    assert by_path["new.py"]["label"] == "переименован"


def test_parse_porcelain_ignores_short_and_blank_lines():
    assert parse_porcelain("\n\n X\n") == []
    assert parse_porcelain("") == []


def test_parse_numstat_and_totals():
    text = "12\t3\tsrc/train.py\n0\t0\tbinary.bin -> b2.bin\n-\t-\tmodel.onnx\n"
    rows = parse_numstat(text)
    assert rows[0] == {"path": "src/train.py", "added": 12, "removed": 3,
                       "binary": False}
    assert rows[2]["binary"] is True and rows[2]["added"] == 0
    assert stat_totals(rows) == (12, 3)


def test_classify_diff_lines():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,2 +1,2 @@\n"
        " context\n"
        "-removed\n"
        "+added\n"
    )
    kinds = [kind for kind, _line in classify_diff_lines(diff)]
    assert kinds == ["meta", "meta", "meta", "hunk", "ctx", "del", "add"]
