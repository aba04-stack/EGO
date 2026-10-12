
import pytest

from alterego_training_hub.tools import ToolError, WorkspaceTools


@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# project\n", encoding="utf-8")
    return WorkspaceTools(tmp_path)


def test_path_escape_is_refused(workspace):
    result = workspace.execute("read_file", {"path": "../outside.txt"})
    assert result["ok"] is False
    assert "рабочей папки" in result["error"]

    result = workspace.execute("write_file", {"path": "/etc/evil.txt", "content": "x"})
    assert result["ok"] is False


def test_list_read_write_roundtrip(workspace, tmp_path):
    listing = workspace.execute("list_files", {"path": ""})
    assert listing["ok"] is True
    assert "src/" in listing["entries"] and "README.md" in listing["entries"]

    read = workspace.execute("read_file", {"path": "src/app.py"})
    assert read["ok"] is True
    assert "hello" in read["content"]

    write = workspace.execute("write_file", {"path": "src/new.py", "content": "x = 1\n"})
    assert write["ok"] is True
    assert write["created"] is True
    assert (tmp_path / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\n"


def test_replace_in_file(workspace):
    result = workspace.execute(
        "replace_in_file",
        {"path": "src/app.py", "find": "hello", "replace": "world"},
    )
    assert result["ok"] is True
    assert result["replaced"] == 1
    content = (workspace.root / "src" / "app.py").read_text(encoding="utf-8")
    assert "world" in content

    missing = workspace.execute(
        "replace_in_file",
        {"path": "src/app.py", "find": "absent", "replace": "x"},
    )
    assert missing["ok"] is False


def test_search_files(workspace):
    result = workspace.execute("search_files", {"pattern": "hello", "glob": "*.py"})
    assert result["ok"] is True
    assert any("app.py" in line for line in result["matches"])

    bad = workspace.execute("search_files", {"pattern": "(unclosed"})
    assert bad["ok"] is False


def test_run_command_capture(workspace):
    result = workspace.execute("run_command", {"command": "python -c \"print('ok-run')\""})
    assert result["ok"] is True
    assert result["returncode"] == 0
    assert "ok-run" in result["output"]

    empty = workspace.execute("run_command", {"command": "   "})
    assert empty["ok"] is False

    missing = workspace.execute("run_command", {"command": "definitely-not-a-real-cmd --x"})
    assert missing["ok"] is False


def test_unknown_tool_and_bad_args(workspace):
    assert workspace.execute("hack", {})["ok"] is False
    assert workspace.execute("read_file", {"wrong": 1})["ok"] is False


def test_readonly_classification():
    assert WorkspaceTools.is_readonly("read_file") is True
    assert WorkspaceTools.is_readonly("run_command") is False
    assert "ls" in WorkspaceTools.describe("run_command", {"command": "ls"})
    assert "a.py" in WorkspaceTools.describe("read_file", {"path": "a.py"})


def test_tool_error_on_missing_root(tmp_path):
    with pytest.raises(ToolError):
        WorkspaceTools(tmp_path / "missing")
