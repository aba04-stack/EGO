"""Plugin catalog: discover and install plugins from curated sources.

Entries describe installable plugins (id, version, description, source).
Sources:
* ``file:<path>``   — copy a local ``.py`` (used for bundled examples/tests);
* ``https://…``     — download a raw plugin file (e.g. from github.com).

Installed plugins land in the plugins folder sandboxed by default; the user
decides what to trust. A catalog is a JSON list of entries — the builtin
one ships with the app, extra catalogs can be loaded from disk.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

CATALOG_SUFFIX = ".py"


class CatalogError(RuntimeError):
    """Catalog input error safe to display."""


@dataclass
class CatalogEntry:
    id: str
    name: str
    version: str = "0"
    description: str = ""
    author: str = ""
    source: str = ""          # file:<path> | https://…
    sha256: str = ""          # optional integrity check of the .py bytes

    def validate(self) -> None:
        if not str(self.id or "").strip():
            raise CatalogError("В записи каталога нет id.")
        if not str(self.source or "").strip():
            raise CatalogError(f"У плагина «{self.id}» не указан источник.")
        if not (self.source.startswith("file:")
                or self.source.startswith("https://")):
            raise CatalogError(
                f"Источник «{self.id}»: file: или https://.")


BUILTIN_CATALOG: list[CatalogEntry] = [
    CatalogEntry(
        id="hello", name="Hello", version="1.0",
        description="Приветственный инструмент — пример плагина.",
        author="AlterEgo", source="file:examples/hello_plugin.py"),
]

# Self-contained copy of the example plugin for installed apps where the
# repo ``examples/`` folder is absent.
BUILTIN_SOURCES: dict[str, str] = {
    "hello": '''\
"""Hello — example AlterEgo plugin."""

PLUGIN = {
    "id": "hello",
    "name": "Hello",
    "version": "1.0",
    "description": "Приветственный инструмент — пример плагина.",
    "tools": {
        "hello_tool": {
            "schema": {"type": "function", "function": {
                "name": "hello_tool",
                "description": "Поздороваться с пользователем",
                "parameters": {"type": "object",
                               "properties": {"name": {"type": "string"}}}}},
            "handler": lambda args: {
                "ok": True,
                "text": f"Привет, {args.get('name') or 'мир'}!"},
            "mutation": False,
        },
    },
}
''',
}


def load_catalog(path: str | Path) -> list[CatalogEntry]:
    """Read a catalog JSON file (a list of entries)."""
    file = Path(path)
    if not file.is_file():
        raise CatalogError(f"Каталог не найден: {file}")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"Некорректный JSON каталога: {exc}") from None
    if not isinstance(raw, list):
        raise CatalogError("Каталог должен содержать список записей.")
    entries: list[CatalogEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CatalogError("Запись каталога должна быть объектом.")
        entry = CatalogEntry(**{key: item.get(key, "")
                                for key in ("id", "name", "version",
                                            "description", "author", "source",
                                            "sha256")})
        entry.validate()
        entries.append(entry)
    return entries


def save_catalog(path: str | Path, entries: list[CatalogEntry]) -> Path:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps([asdict(entry) for entry in entries],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return file


def _fetch_source(entry: CatalogEntry, *, base_dir: Path) -> bytes:
    source = entry.source
    if source.startswith("file:"):
        path = Path(source[len("file:"):])
        if not path.is_absolute():
            path = base_dir / path
        try:
            return path.read_bytes()
        except OSError:
            embedded = BUILTIN_SOURCES.get(entry.id)
            if embedded is not None:
                return embedded.encode("utf-8")
            raise CatalogError(
                f"Не удалось прочитать «{entry.id}»: {path}") from None
    try:
        with urllib.request.urlopen(source, timeout=30) as response:
            return response.read()
    except Exception as exc:
        raise CatalogError(f"Не удалось скачать «{entry.id}»: {exc}") from None


def install_entry(entry: CatalogEntry, plugins_dir: str | Path,
                  *, base_dir: str | Path | None = None) -> Path:
    """Download/copy the plugin file into the plugins folder."""
    import hashlib

    entry.validate()
    directory = Path(plugins_dir)
    directory.mkdir(parents=True, exist_ok=True)
    data = _fetch_source(entry, base_dir=Path(base_dir or Path.cwd()))
    if not data.strip():
        raise CatalogError(f"Плагин «{entry.id}» пуст.")
    if entry.sha256:
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.sha256.strip().lower():
            raise CatalogError(
                f"Контрольная сумма «{entry.id}» не совпала — файл не установлен.")
    if not data.lstrip().startswith(b"#") and b"PLUGIN" not in data:
        raise CatalogError(f"Файл «{entry.id}» не похож на плагин (нет PLUGIN).")
    target = directory / f"{entry.id}{CATALOG_SUFFIX}"
    target.write_bytes(data)
    return target


def uninstall(plugin_id: str, plugins_dir: str | Path) -> bool:
    """Remove an installed plugin file; True when something was removed."""
    target = Path(plugins_dir) / f"{plugin_id}{CATALOG_SUFFIX}"
    if target.is_file():
        target.unlink()
        return True
    return False
