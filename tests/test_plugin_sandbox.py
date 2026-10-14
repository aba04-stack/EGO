"""Tests for the plugin sandbox: isolation, timeouts, trust levels."""
from __future__ import annotations

from alterego_training_hub.plugin_sandbox import (
    describe_plugin,
    run_tool,
    static_trusted,
)
from alterego_training_hub.plugins import PluginManager

SAFE_PLUGIN = '''
STATE = {"calls": 0}

def greet(args):
    STATE["calls"] += 1
    return {"ok": True, "text": "hi", "calls": STATE["calls"]}

PLUGIN = {
    "id": "safe",
    "name": "Safe",
    "version": "1.0",
    "tools": {
        "greet": {
            "schema": {"type": "function", "function": {
                "name": "greet", "description": "hi",
                "parameters": {"type": "object", "properties": {}}}},
            "handler": greet,
            "mutation": False,
        },
    },
}
'''

TRUSTED_PLUGIN = SAFE_PLUGIN.replace('"name": "Safe"', '"name": "Trusted", '
                                     '"trusted": True, "id": "trusted"')

IMPORT_VIOLATION = "import os\nPLUGIN = {'id': 'evil', 'tools': {}}"

FILE_VIOLATION = '''
def leak(args):
    return {"data": open("/etc/passwd").read()}

PLUGIN = {"id": "leak", "tools": {"leak": {
    "schema": {"type": "function", "function": {
        "name": "leak", "description": "x",
        "parameters": {"type": "object", "properties": {}}}},
    "handler": leak}}}
'''

LOOP_PLUGIN = '''
def hang(args):
    while True:
        pass

PLUGIN = {"id": "hang", "tools": {"hang": {
    "schema": {"type": "function", "function": {
        "name": "hang", "description": "x",
        "parameters": {"type": "object", "properties": {}}}},
    "handler": hang}}}
'''


def test_sandboxed_plugin_loads_and_runs(tmp_path):
    (tmp_path / "safe.py").write_text(SAFE_PLUGIN, encoding="utf-8")
    manager = PluginManager(tmp_path)
    plugins = manager.load_all()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.ok and plugin.trusted is False
    assert plugin.tools[0].sandboxed is True

    handler = manager.tool_handlers(plugins)["greet"]
    first = handler({})
    assert first["ok"] is True and first["text"] == "hi"
    # fresh worker per call: module state never leaks between calls
    second = handler({})
    assert second["calls"] == 1 and first["calls"] == 1


def test_trusted_plugin_runs_in_process_with_state(tmp_path):
    (tmp_path / "trusted.py").write_text(TRUSTED_PLUGIN, encoding="utf-8")
    manager = PluginManager(tmp_path)
    plugin = manager.load_all()[0]
    assert plugin.ok and plugin.trusted is True
    assert plugin.tools[0].sandboxed is False
    handler = manager.tool_handlers()[ "greet"]
    assert handler({})["calls"] == 1
    assert handler({})["calls"] == 2  # same module namespace: state persists


def test_sandbox_blocks_imports_and_files(tmp_path):
    (tmp_path / "evil.py").write_text(IMPORT_VIOLATION, encoding="utf-8")
    manager = PluginManager(tmp_path)
    plugin = manager.load_all()[0]
    assert plugin.ok is False
    assert "запрещён в песочнице" in plugin.error

    (tmp_path / "leak.py").write_text(FILE_VIOLATION, encoding="utf-8")
    leak = PluginManager(tmp_path).load_all()[0]
    assert leak.ok is False or leak.tools  # loads (open used only at call time)
    result = run_tool(tmp_path / "leak.py", "leak", {})
    assert result["ok"] is False  # open() does not exist in the sandbox


def test_sandbox_kills_infinite_loops(tmp_path):
    (tmp_path / "hang.py").write_text(LOOP_PLUGIN, encoding="utf-8")
    result = run_tool(tmp_path / "hang.py", "hang", {}, timeout=2.0)
    assert result["ok"] is False
    assert "таймаут" in result["error"]


def test_describe_reports_metadata(tmp_path):
    (tmp_path / "safe.py").write_text(SAFE_PLUGIN, encoding="utf-8")
    meta, error = describe_plugin(tmp_path / "safe.py")
    assert error == ""
    assert meta["id"] == "safe" and meta["name"] == "Safe"
    assert meta["tools"][0]["name"] == "greet"
    assert "handler" not in meta["tools"][0]  # never expose callables


def test_static_trust_detection(tmp_path):
    trusted = tmp_path / "t.py"
    trusted.write_text(TRUSTED_PLUGIN, encoding="utf-8")
    plain = tmp_path / "p.py"
    plain.write_text(SAFE_PLUGIN, encoding="utf-8")
    assert static_trusted(trusted) is True
    assert static_trusted(plain) is False
    assert static_trusted(tmp_path / "missing.py") is False


def test_user_trust_override_persists(tmp_path):
    (tmp_path / "safe.py").write_text(SAFE_PLUGIN, encoding="utf-8")
    manager = PluginManager(tmp_path)
    assert manager.load_all()[0].trusted is False
    manager.set_trust("safe", True)
    assert manager.is_trusted(tmp_path / "safe.py") is True
    plugin = manager.load_all()[0]
    assert plugin.trusted is True and plugin.tools[0].sandboxed is False
    manager.set_trust("safe", False)
    assert manager.load_all()[0].trusted is False
