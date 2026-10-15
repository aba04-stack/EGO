"""Tests for the plugin system: isolation, tools, enable flags."""
from __future__ import annotations

import json

from alterego_training_hub.plugins import PluginManager

GOOD_PLUGIN = '''
PLUGIN = {
    "id": "hello",
    "name": "Hello",
    "version": "1.2",
    "description": "тестовый плагин",
    "tools": {
        "hello_tool": {
            "schema": {"type": "function", "function": {
                "name": "hello_tool",
                "description": "поздороваться",
                "parameters": {"type": "object", "properties": {}}}},
            "handler": lambda args: {"ok": True, "text": "hi"},
            "mutation": False,
        },
        "hello_write": {
            "schema": {"type": "function", "function": {
                "name": "hello_write",
                "description": "что-то изменить",
                "parameters": {"type": "object", "properties": {}}}},
            "handler": lambda args: {"ok": True},
            "mutation": True,
        },
    },
}
'''

BAD_PLUGIN = "PLUGIN = {'tools': {'x': {'schema': {}, 'handler': None}}}"
BROKEN_PLUGIN = "raise RuntimeError('плохой плагин')"


def test_plugin_load_and_tools(tmp_path):
    (tmp_path / "hello.py").write_text(GOOD_PLUGIN, encoding="utf-8")
    manager = PluginManager(tmp_path)
    plugins = manager.load_all()
    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin.ok and plugin.enabled
    assert plugin.name == "Hello" and plugin.version == "1.2"
    assert {tool.name for tool in plugin.tools} == {"hello_tool", "hello_write"}

    schemas = manager.tool_schemas(plugins)
    assert [schema["function"]["name"] for schema in schemas] == \
        ["hello_tool", "hello_write"]
    handlers = manager.tool_handlers(plugins)
    assert handlers["hello_tool"]({}) == {"ok": True, "text": "hi"}
    assert manager.tool_mutations(plugins) == {"hello_write"}


def test_plugin_isolation_and_validation(tmp_path):
    (tmp_path / "bad.py").write_text(BAD_PLUGIN, encoding="utf-8")
    (tmp_path / "broken.py").write_text(BROKEN_PLUGIN, encoding="utf-8")
    (tmp_path / "good.py").write_text(GOOD_PLUGIN, encoding="utf-8")
    manager = PluginManager(tmp_path)
    plugins = {plugin.id: plugin for plugin in manager.load_all()}
    assert plugins["broken"].ok is False and "плохой плагин" in \
        plugins["broken"].error
    assert plugins["bad"].ok is False  # handler is not callable
    assert plugins["hello"].ok is True  # one bad plugin never breaks loading
    assert manager.tool_schemas()  # only the good one


def test_plugin_enable_flags_persist(tmp_path):
    (tmp_path / "hello.py").write_text(GOOD_PLUGIN, encoding="utf-8")
    manager = PluginManager(tmp_path)
    manager.set_enabled("hello", False)
    flags = json.loads(manager.manifest_path.read_text(encoding="utf-8"))
    assert flags == {"hello": False}
    plugins = manager.load_all()
    assert plugins[0].enabled is False
    assert manager.tool_schemas(plugins) == []
    assert manager.tool_handlers(plugins) == {}

    manager.set_enabled("hello", True)
    assert manager.load_all()[0].enabled is True


def test_plugin_without_payload(tmp_path):
    (tmp_path / "empty.py").write_text("x = 1\n", encoding="utf-8")
    manager = PluginManager(tmp_path)
    plugin = manager.load_all()[0]
    assert plugin.ok is False and "PLUGIN" in plugin.error
    assert PluginManager(tmp_path / "нет такой").load_all() == []
