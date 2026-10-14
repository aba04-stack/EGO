"""Customizable application hotkeys: defaults, validation, conflict checks.

Actions cover the app-level shortcuts (navigation, panels, palettes, help).
Editor-internal keys stay fixed to avoid breaking the editing workflow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SEQ_RE = re.compile(r"^(<[^<>]+>|[A-Za-zА-Яа-я0-9])$")


@dataclass(frozen=True)
class HotkeyAction:
    id: str
    label: str
    default_key: str
    description: str = ""


DEFAULT_HOTKEYS: dict[str, HotkeyAction] = {
    action.id: action for action in [
        HotkeyAction("page.editor", "Страница: Редактор кода", "<Control-Key-1>"),
        HotkeyAction("page.workspace", "Страница: Рабочая папка", "<Control-Key-2>"),
        HotkeyAction("page.models", "Страница: Модели", "<Control-Key-3>"),
        HotkeyAction("page.datasets", "Страница: Датасеты", "<Control-Key-4>"),
        HotkeyAction("page.model", "Страница: Модель и прогресс", "<Control-Key-5>"),
        HotkeyAction("page.playground", "Страница: Playground", "<Control-Key-6>"),
        HotkeyAction("page.training", "Страница: Обучение", "<Control-Key-7>"),
        HotkeyAction("page.gpu", "Страница: Внешние GPU", "<Control-Key-8>"),
        HotkeyAction("page.servers", "Страница: Серверы", "<Control-Key-9>"),
        HotkeyAction("page.settings", "Страница: Настройки", "<Control-Key-0>"),
        HotkeyAction("page.chat", "Панель чата", "<Control-k>"),
        HotkeyAction("page.search", "Поиск", "<Control-Shift-F>"),
        HotkeyAction("panel.toggle", "Показать/скрыть нижнюю панель", "<Control-j>"),
        HotkeyAction("panel.problems", "Панель «Проблемы»", "<Control-Shift-M>"),
        HotkeyAction("panel.git", "Панель «Git»", "<Control-Shift-G>"),
        HotkeyAction("palette.files", "Палитра: быстрый переход", "<Control-p>"),
        HotkeyAction("palette.commands", "Палитра: команды", "<Control-Shift-P>"),
        HotkeyAction("app.refresh", "Обновить страницу", "<F5>"),
        HotkeyAction("app.help", "Справка по клавишам", "<F1>"),
    ]
}


class HotkeyError(RuntimeError):
    """Hotkey input error safe to display."""


def validate_key(sequence: str) -> str:
    """Accept a tkinter bind sequence like ``<Control-j>`` or a single key."""
    text = str(sequence or "").strip()
    if not text or not _SEQ_RE.match(text):
        raise HotkeyError(
            f"Недопустимая комбинация: «{text}». Пример: <Control-j> или <F5>.")
    if len(text) > 40:
        raise HotkeyError("Слишком длинная комбинация.")
    return text


def resolve_hotkeys(custom: dict | None = None) -> dict[str, str]:
    """Merge user bindings over defaults; unknown actions and bad keys drop."""
    resolved = {action_id: action.default_key
                for action_id, action in DEFAULT_HOTKEYS.items()}
    for action_id, key in dict(custom or {}).items():
        if action_id not in DEFAULT_HOTKEYS:
            continue
        try:
            resolved[action_id] = validate_key(key)
        except HotkeyError:
            continue
    return resolved


def detect_conflicts(bindings: dict[str, str]) -> list[tuple[str, list[str]]]:
    """Return (key, [action ids]) for keys bound to several actions."""
    by_key: dict[str, list[str]] = {}
    for action_id, key in bindings.items():
        by_key.setdefault(key, []).append(action_id)
    return sorted((key, sorted(ids)) for key, ids in by_key.items()
                  if len(ids) > 1)


def save_hotkeys(bindings: dict[str, str]) -> dict[str, str]:
    """Validate a full binding map and keep only changed, valid entries."""
    changes: dict[str, str] = {}
    for action_id, key in bindings.items():
        if action_id not in DEFAULT_HOTKEYS:
            raise HotkeyError(f"Неизвестное действие: {action_id}")
        validated = validate_key(key)
        if validated != DEFAULT_HOTKEYS[action_id].default_key:
            changes[action_id] = validated
    conflicts = detect_conflicts(resolve_hotkeys(changes))
    if conflicts:
        detail = "; ".join(f"{key} → {', '.join(ids)}"
                           for key, ids in conflicts)
        raise HotkeyError(f"Конфликт клавиш: {detail}.")
    return changes
