"""Interface localization: curated RU/EN string packs with safe fallbacks.

Coverage grows progressively; every key exists in every language pack.
``t(key)`` falls back to Russian, then to the key itself — a missing
translation must never break the UI.
"""
from __future__ import annotations

LANGUAGES: dict[str, str] = {"ru": "Русский", "en": "English"}
DEFAULT_LANGUAGE = "ru"

_STRINGS_RU: dict[str, str] = {
    "brand.subtitle": "LLM Studio",
    "brand.version": "v0.19 · локальный контур",
    "nav.development": "РАЗРАБОТКА",
    "nav.editor": "Редактор кода",
    "nav.workspace": "Рабочая папка",
    "nav.search": "Поиск",
    "nav.library": "БИБЛИОТЕКА",
    "nav.models": "Модели",
    "nav.datasets": "Датасеты",
    "nav.model": "Модель и прогресс",
    "nav.experiments": "ЭКСПЕРИМЕНТЫ",
    "nav.playground": "Playground",
    "nav.training": "Обучение",
    "nav.gpu": "Внешние GPU",
    "nav.system": "СИСТЕМА",
    "nav.servers": "Серверы",
    "nav.connectors": "Коннекторы",
    "nav.settings": "Настройки",
    "status.ready": "Готово · F1 — горячие клавиши",
    "chat.title": "Наставник",
    "chat.mode": "Режим",
    "platform.title": "Платформа: язык и раскладки",
    "platform.keys_title": "Платформа: клавиши и плагины",
    "platform.language": "Язык интерфейса",
    "platform.layout": "Раскладка",
    "platform.apply_layout": "Применить раскладку",
    "platform.save_layout": "Сохранить текущую как…",
    "platform.hotkeys_hint": "Формат: <Control-Key-5>, <F5>, <Control-j>. "
                             "Изменения вступят в силу после перезапуска.",
    "platform.save_hotkeys": "Сохранить клавиши",
    "platform.reset_hotkeys": "Сбросить к умолчаниям",
    "platform.plugins": "Плагины (plugins/*.py)",
    "platform.reload_plugins": "Перезагрузить плагины",
    "platform.language_note": "Смена языка применяется после перезапуска.",
}

_STRINGS_EN: dict[str, str] = {
    "brand.subtitle": "LLM Studio",
    "brand.version": "v0.19 · local workspace",
    "nav.development": "DEVELOPMENT",
    "nav.editor": "Code editor",
    "nav.workspace": "Workspace",
    "nav.search": "Search",
    "nav.library": "LIBRARY",
    "nav.models": "Models",
    "nav.datasets": "Datasets",
    "nav.model": "Model & progress",
    "nav.experiments": "EXPERIMENTS",
    "nav.playground": "Playground",
    "nav.training": "Training",
    "nav.gpu": "Cloud GPU",
    "nav.system": "SYSTEM",
    "nav.servers": "Servers",
    "nav.connectors": "Connectors",
    "nav.settings": "Settings",
    "status.ready": "Ready · F1 — keyboard shortcuts",
    "chat.title": "Mentor",
    "chat.mode": "Mode",
    "platform.title": "Platform: language & layouts",
    "platform.keys_title": "Platform: hotkeys & plugins",
    "platform.language": "Interface language",
    "platform.layout": "Layout",
    "platform.apply_layout": "Apply layout",
    "platform.save_layout": "Save current as…",
    "platform.hotkeys_hint": "Format: <Control-Key-5>, <F5>, <Control-j>. "
                             "Changes apply after restart.",
    "platform.save_hotkeys": "Save hotkeys",
    "platform.reset_hotkeys": "Reset to defaults",
    "platform.plugins": "Plugins (plugins/*.py)",
    "platform.reload_plugins": "Reload plugins",
    "platform.language_note": "Language changes apply after restart.",
}

STRINGS: dict[str, dict[str, str]] = {"ru": _STRINGS_RU, "en": _STRINGS_EN}

_current = DEFAULT_LANGUAGE


def set_language(lang: str) -> str:
    global _current
    _current = str(lang or "").strip().lower()
    if _current not in STRINGS:
        _current = DEFAULT_LANGUAGE
    return _current


def current_language() -> str:
    return _current


def t(key: str, default: str | None = None) -> str:
    """Translate ``key``; fall back to Russian, then to ``default``/key."""
    pack = STRINGS.get(_current, {})
    if key in pack:
        return pack[key]
    if key in _STRINGS_RU:
        return _STRINGS_RU[key]
    return default if default is not None else key


def missing_keys() -> list[str]:
    """Keys absent from some language pack (for tests/quality checks)."""
    all_keys = set().union(*(set(pack) for pack in STRINGS.values()))
    return sorted(key for key in all_keys
                  if any(key not in pack for pack in STRINGS.values()))
