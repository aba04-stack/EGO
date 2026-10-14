"""Tests for diff preview and the diff_files tool (agent precision)."""
from __future__ import annotations

from alterego_training_hub.tools import WorkspaceTools, preview_diff


def test_preview_diff_unified_and_clipped():
    diff = preview_diff("a\nb\nc\n", "a\nB\nc\n", "x.txt")
    assert diff.startswith("--- a/x.txt")
    assert "+++ b/x.txt" in diff
    assert "-b" in diff and "+B" in diff
    assert preview_diff("same\n", "same\n", "x.txt") == "(без изменений)"
    long_old = "".join(f"line {i}\n" for i in range(100))
    long_new = "".join(f"LINE {i}\n" for i in range(100))
    clipped = preview_diff(long_old, long_new, "big.txt", max_lines=10)
    assert "ещё" in clipped
    assert len(clipped.splitlines()) <= 12


def test_preview_change_for_write_and_replace(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    tools = WorkspaceTools(root)
    (root / "a.txt").write_text("hello\n", encoding="utf-8")

    diff = tools.preview_change(
        "write_file", {"path": "a.txt", "content": "world\n"})
    assert "+world" in diff and "-hello" in diff

    diff = tools.preview_change(
        "replace_in_file", {"path": "a.txt", "find": "hello",
                            "replace": "привет", "count": 0})
    assert "+привет" in diff and "-hello" in diff

    # New file preview is a pure addition.
    diff = tools.preview_change(
        "write_file", {"path": "new.txt", "content": "fresh\n"})
    assert "+fresh" in diff and "--- a/new.txt" in diff

    # Not applicable / unreadable → empty string, never raises.
    assert tools.preview_change("run_command", {"command": "ls"}) == ""
    assert tools.preview_change("write_file", {}) == ""
    assert tools.preview_change("replace_in_file",
                                {"path": "missing.txt", "find": "x",
                                 "replace": "y"}) == ""


def test_diff_files_tool(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    tools = WorkspaceTools(root)
    (root / "one.txt").write_text("alpha\n", encoding="utf-8")
    (root / "two.txt").write_text("beta\n", encoding="utf-8")
    (root / "copy.txt").write_text("alpha\n", encoding="utf-8")

    result = tools.execute("diff_files",
                           {"path_a": "one.txt", "path_b": "two.txt"})
    assert result["ok"] and result["same"] is False
    assert "-alpha" in result["diff"] and "+beta" in result["diff"]

    result = tools.execute("diff_files",
                           {"path_a": "one.txt", "path_b": "copy.txt"})
    assert result["ok"] and result["same"] is True and result["diff"] == ""

    result = tools.execute("diff_files",
                           {"path_a": "one.txt", "path_b": "missing.txt"})
    assert result["ok"] is False

    assert WorkspaceTools.is_readonly("diff_files") is True
