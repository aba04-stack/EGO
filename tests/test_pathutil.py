"""Tests for safe user-supplied file-name resolution."""
from __future__ import annotations

import pytest

from alterego_training_hub.pathutil import PathSafetyError, safe_child_path


def test_safe_child_path_accepts_names_and_subfolders(tmp_path):
    assert safe_child_path(tmp_path, "train.py") == tmp_path.resolve() / "train.py"
    nested = safe_child_path(tmp_path, "models/tiny/config.json")
    assert nested == tmp_path.resolve() / "models" / "tiny" / "config.json"


def test_safe_child_path_rejects_traversal_and_absolute(tmp_path):
    for bad in ("..", "../evil.py", "a/../../b", "/etc/passwd", "",
                "  ", "a\x00b", "."):
        with pytest.raises(PathSafetyError):
            safe_child_path(tmp_path, bad)
