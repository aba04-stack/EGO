"""Plugin system: third-party agent tools loaded from a plugins folder.

A plugin is a single ``*.py`` file exposing a module-level ``PLUGIN`` dict::

    PLUGIN = {
        "id": "hello", "name": "Hello", "version": "1.0",
        "description": "Приветствие",
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
"""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLUGIN_SUFFIX = ".py"
MANIFEST_NAME = "plugins.json"


class PluginError(RuntimeError):
    """Plugin input error safe to display."""


@dataclass
class PluginTool:
    name: str
    schema: dict[str, Any]
    handler: Any
    mutation: bool = False


@dataclass
class LoadedPlugin:
    id: str
    name: str
    version: str = "0"
    description: str = ""
    path: str = ""
    enabled: bool = True
    tools: list[PluginTool] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class PluginManager:
    """Discover/load plugins and persist per-plugin enable flags."""

    def __init__(self, plugins_dir: str | Path):
        self.plugins_dir = Path(plugins_dir)
        self.manifest_path = self.plugins_dir / MANIFEST_NAME

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
            return self._build(path, payload, flags)
        except Exception as exc:  # noqa: BLE001 - plugin isolation
            return LoadedPlugin(id=path.stem, name=path.stem, path=str(path),
                                enabled=False,
                                error=f"{type(exc).__name__}: {exc}")
        finally:
            sys.modules.pop(module_id, None)

    def _build(self, path: Path, payload: dict, flags: dict[str, bool]) \
            -> LoadedPlugin:
        plugin_id = str(payload.get("id") or path.stem).strip() or path.stem
        plugin = LoadedPlugin(
            id=plugin_id,
            name=str(payload.get("name") or plugin_id),
            version=str(payload.get("version") or "0"),
            description=str(payload.get("description") or ""),
            path=str(path),
            enabled=flags.get(plugin_id, True),
        )
        tools = payload.get("tools") or {}
        if not isinstance(tools, dict):
            plugin.error = "поле tools должно быть словарём"
            return plugin
        for name, spec in tools.items():
            if not isinstance(spec, dict):
                plugin.error = f"инструмент «{name}» описан не объектом"
                return plugin
            schema = spec.get("schema")
            handler = spec.get("handler")
            function = (schema or {}).get("function", {}) if isinstance(
                schema, dict) else {}
            if not isinstance(schema, dict) or not function.get("name") \
                    or not callable(handler):
                plugin.error = f"инструмент «{name}»: нужен schema.function.name "\
                               "и handler"
                return plugin
            plugin.tools.append(PluginTool(
                name=str(function.get("name")), schema=schema,
                handler=handler, mutation=bool(spec.get("mutation"))))
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
