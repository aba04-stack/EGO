"""Plugin system: third-party agent tools loaded from a plugins folder.

A plugin is a single ``*.py`` file exposing a module-level ``PLUGIN`` dict::

    PLUGIN = {
        "id": "hello", "name": "Hello", "version": "1.0",
        "description": "Приветствие",
        "trusted": True,   # optional: run in-process (default: sandboxed)
        "tools": {
            "hello_tool": {
                "schema": {"type": "function", "function": {...}},
                "handler": lambda args: {"ok": True, "text": "hi"},
                "mutation": False,
            }
        }
    }

One broken plugin never breaks the app: errors are recorded per plugin.
Enable/disable flags persist in ``plugins.json`` next to the plugin files.

Trust: ``PLUGIN["trusted"] = True`` is detected statically via AST (no code
runs in-process for untrusted plugins); user overrides persist in
``plugins_trust.json``. Untrusted plugins are inspected and executed in a
restricted worker subprocess with timeouts (see ``plugin_sandbox``).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plugin_sandbox import (build_meta, describe_plugin, run_tool,
                             static_trusted)

PLUGIN_SUFFIX = ".py"
MANIFEST_NAME = "plugins.json"
TRUST_NAME = "plugins_trust.json"


class PluginError(RuntimeError):
    """Plugin input error safe to display."""


@dataclass
class PluginTool:
    name: str
    schema: dict[str, Any]
    handler: Any
    mutation: bool = False
    sandboxed: bool = False


@dataclass
class LoadedPlugin:
    id: str
    name: str
    version: str = "0"
    description: str = ""
    path: str = ""
    enabled: bool = True
    trusted: bool = False
    tools: list[PluginTool] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class PluginManager:
    """Discover/load plugins and persist per-plugin flags."""

    def __init__(self, plugins_dir: str | Path):
        self.plugins_dir = Path(plugins_dir)
        self.manifest_path = self.plugins_dir / MANIFEST_NAME
        self.trust_path = self.plugins_dir / TRUST_NAME

    # ----------------------------------------------------------- manifest
    def _flags(self) -> dict[str, bool]:
        if not self.manifest_path.exists():
            return {}
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(key): bool(value) for key, value in raw.items()}

    def _save_flags(self, flags: dict[str, bool]) -> Path:
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(flags, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.manifest_path

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        flags = self._flags()
        flags[str(plugin_id)] = bool(enabled)
        self._save_flags(flags)

    # -------------------------------------------------------- trust flags
    def _trust_overrides(self) -> dict[str, bool]:
        if not self.trust_path.exists():
            return {}
        try:
            raw = json.loads(self.trust_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(key): bool(value) for key, value in raw.items()}

    def set_trust(self, plugin_id: str, trusted: bool) -> None:
        """Persist a user trust decision for a plugin."""
        overrides = self._trust_overrides()
        overrides[str(plugin_id)] = bool(trusted)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.trust_path.write_text(
            json.dumps(overrides, ensure_ascii=False, indent=2),
            encoding="utf-8")

    def is_trusted(self, path: Path, plugin_id: str | None = None) -> bool:
        overrides = self._trust_overrides()
        key = str(plugin_id or path.stem)
        if key in overrides:
            return overrides[key]
        return static_trusted(path)

    # -------------------------------------------------------------- load
    def discover(self) -> list[Path]:
        if not self.plugins_dir.is_dir():
            return []
        return sorted(self.plugins_dir.glob(f"*{PLUGIN_SUFFIX}"))

    def load_all(self) -> list[LoadedPlugin]:
        flags = self._flags()
        loaded: list[LoadedPlugin] = []
        for path in self.discover():
            loaded.append(self._load_one(path, flags))
        # Drop stale manifest ids so the file stays tidy.
        known = {plugin.id for plugin in loaded}
        flags = {key: value for key, value in flags.items() if key in known}
        if flags or self.manifest_path.exists():
            self._save_flags(flags)
        return loaded

    def _load_one(self, path: Path, flags: dict[str, bool]) -> LoadedPlugin:
        if not self.is_trusted(path):
            return self._load_sandboxed(path, flags)
        module_id = f"alterego_plugin_{path.stem}_{uuid.uuid4().hex[:6]}"
        try:
            spec = importlib.util.spec_from_file_location(module_id, path)
            if spec is None or spec.loader is None:
                raise PluginError("не удалось создать спецификацию модуля")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_id] = module
            spec.loader.exec_module(module)
            payload = getattr(module, "PLUGIN", None)
            if not isinstance(payload, dict):
                raise PluginError("в модуле нет словаря PLUGIN")
            return self._build(path, payload, flags, trusted=True)
        except Exception as exc:  # noqa: BLE001 - plugin isolation
            return LoadedPlugin(id=path.stem, name=path.stem, path=str(path),
                                enabled=False,
                                error=f"{type(exc).__name__}: {exc}")
        finally:
            sys.modules.pop(module_id, None)

    def _load_sandboxed(self, path: Path, flags: dict[str, bool]) \
            -> LoadedPlugin:
        meta, error = describe_plugin(path)
        if error:
            return LoadedPlugin(id=path.stem, name=path.stem, path=str(path),
                                enabled=False, error=error)
        plugin_id = str(meta.get("id") or path.stem)
        plugin = LoadedPlugin(
            id=plugin_id,
            name=str(meta.get("name") or path.stem),
            version=str(meta.get("version") or "0"),
            description=str(meta.get("description") or ""),
            path=str(path),
            enabled=flags.get(plugin_id, True),
            trusted=False,
        )
        for spec in meta.get("tools") or []:
            name = str(spec.get("name"))
            plugin.tools.append(PluginTool(
                name=name,
                schema=dict(spec.get("schema") or {}),
                handler=self._sandbox_handler(path, name),
                mutation=bool(spec.get("mutation")),
                sandboxed=True))
        return plugin

    @staticmethod
    def _sandbox_handler(path: Path, tool_name: str):
        def call(args: dict) -> dict:
            return run_tool(path, tool_name, dict(args or {}))

        call.__name__ = tool_name
        return call

    def _build(self, path: Path, payload: dict, flags: dict[str, bool],
               *, trusted: bool = False) -> LoadedPlugin:
        meta, error = build_meta(payload, path)
        plugin = LoadedPlugin(
            id=meta["id"], name=meta["name"], version=meta["version"],
            description=meta["description"], path=str(path),
            enabled=flags.get(meta["id"], True), trusted=trusted)
        if error:
            plugin.error = error
            return plugin
        tools = payload.get("tools") or {}
        for name, spec in tools.items():
            function = (spec.get("schema") or {}).get("function", {})
            plugin.tools.append(PluginTool(
                name=str(function.get("name")), schema=spec.get("schema"),
                handler=spec.get("handler"),
                mutation=bool(spec.get("mutation")),
                sandboxed=not trusted))
        return plugin

    # ----------------------------------------------------------- queries
    def tool_schemas(self, plugins: list[LoadedPlugin] | None = None) \
            -> list[dict[str, Any]]:
        return [tool.schema for plugin in (plugins or self.load_all())
                if plugin.ok and plugin.enabled
                for tool in plugin.tools]

    def tool_handlers(self, plugins: list[LoadedPlugin] | None = None) \
            -> dict[str, Any]:
        return {tool.name: tool.handler
                for plugin in (plugins or self.load_all())
                if plugin.ok and plugin.enabled for tool in plugin.tools}

    def tool_mutations(self, plugins: list[LoadedPlugin] | None = None) -> set[str]:
        return {tool.name for plugin in (plugins or self.load_all())
                if plugin.ok and plugin.enabled for tool in plugin.tools
                if tool.mutation}
