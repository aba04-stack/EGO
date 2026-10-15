"""Settings sync between machines via a portable JSON bundle.

The bundle holds only ``AppSettings`` fields (secrets stay in the system
keyring and are never exported). A sync folder (e.g. OneDrive/Dropbox)
receives ``alterego-settings.json``; pull applies a bundle only when it is
newer than the last synced timestamp (last write wins).
"""
from __future__ import annotations

import json
import time
from dataclasses import fields as dataclass_fields
from pathlib import Path

SYNC_FILENAME = "alterego-settings.json"
BUNDLE_VERSION = 1


class SettingsSyncError(RuntimeError):
    """Settings sync input error safe to display."""


def _field_names(settings) -> set[str]:
    return {f.name for f in dataclass_fields(settings)}


def bundle(settings) -> dict:
    """Snapshot exportable settings (no secrets) with a timestamp."""
    names = _field_names(settings)
    return {
        "app": "alterego-training-hub",
        "version": BUNDLE_VERSION,
        "saved_at": time.time(),
        "fields": {name: getattr(settings, name) for name in sorted(names)},
    }


def export_settings(path: str | Path, settings) -> Path:
    """Write a bundle to ``path``; parent folders are created."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(bundle(settings), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return file


def import_bundle(path: str | Path) -> dict:
    """Read and validate a bundle; raises SettingsSyncError on damage."""
    file = Path(path)
    if not file.is_file():
        raise SettingsSyncError(f"Файл настроек не найден: {file}")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsSyncError(f"Некорректный JSON настроек: {exc}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("fields"), dict):
        raise SettingsSyncError("Файл настроек должен содержать объект fields.")
    if raw.get("app") != "alterego-training-hub":
        raise SettingsSyncError("Файл не является экспортом EGO.")
    return raw


def apply_bundle(settings, raw: dict) -> list[str]:
    """Apply whitelisted fields with type checks; returns changed names.

    Unknown fields and type mismatches are skipped silently — a bundle from
    a newer version must never break an older install.
    """
    if not isinstance(raw, dict):
        raise SettingsSyncError("Экспорт настроек повреждён.")
    values = raw.get("fields") if "fields" in raw else raw
    if not isinstance(values, dict):
        raise SettingsSyncError("Экспорт настроек повреждён.")
    names = _field_names(settings)
    changed: list[str] = []
    for name, value in sorted(values.items()):
        if name not in names:
            continue
        current = getattr(settings, name)
        if isinstance(current, bool):
            if not isinstance(value, bool):
                continue
        elif isinstance(current, (int, float)) and not isinstance(current, bool):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
        elif isinstance(current, str):
            if not isinstance(value, str):
                continue
        elif isinstance(current, dict):
            if not isinstance(value, dict):
                continue
        if current != value:
            setattr(settings, name, value)
            changed.append(name)
    return changed


def push(settings, folder: str | Path) -> Path:
    """Write the bundle into the sync folder and remember the timestamp."""
    directory = Path(folder).expanduser()
    if not str(folder or "").strip():
        raise SettingsSyncError("Не выбрана папка синхронизации.")
    directory.mkdir(parents=True, exist_ok=True)
    file = export_settings(directory / SYNC_FILENAME, settings)
    try:
        settings.synced_at = json.loads(
            file.read_text(encoding="utf-8"))["saved_at"]
    except (OSError, json.JSONDecodeError, KeyError):
        settings.synced_at = time.time()
    return file


def pull(settings, folder: str | Path) -> tuple[bool, list[str]]:
    """Apply the bundle from the sync folder when it is newer.

    Returns (applied?, changed field names).
    """
    file = Path(folder).expanduser() / SYNC_FILENAME
    if not file.is_file():
        return False, []
    raw = import_bundle(file)
    saved_at = float(raw.get("saved_at") or 0.0)
    if saved_at <= float(getattr(settings, "synced_at", 0.0) or 0.0):
        return False, []
    changed = apply_bundle(settings, raw)
    settings.synced_at = saved_at
    return True, changed
