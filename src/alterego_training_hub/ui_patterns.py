"""UX patterns borrowed from modern IDEs (этап 28), as pure testable logic.

Benchmarked against VS Code/Cursor (activity bar, status bar, Ctrl+K palette,
primary action top-right) and ChatGPT desktop (icons by the chat input,
session list with search).  No tkinter here — widgets consume these helpers.
"""
from __future__ import annotations

from .i18n import t

# One icon per page for the compact (activity-bar) sidebar mode.
NAV_ICONS: dict[str, str] = {
    "editor": "📝", "workspace": "📁", "search": "🔎",
    "models": "🧊", "datasets": "🗂", "model": "🎛",
    "playground": "🧪", "training": "🏋", "gpu": "🖥",
    "servers": "🌐", "connectors": "🔌", "settings": "⚙", "chat": "💬",
}

# The one primary action per page, shown top-right in the page header.
PRIMARY_ACTIONS: dict[str, tuple[str, str]] = {
    "training": (t(t('Запустить')), "start_training"),
    "models": (t(t('Добавить')), "add_entry"),
    "datasets": (t(t('Сканировать папку…')), "scan_folder"),
    "model": (t(t('Оценка наставника')), "request_assessment"),
    "playground": (t(t('Запустить')), "run_single"),
    "gpu": (t(t('Обновить')), "refresh_jobs"),
}


def nav_icon(key: str) -> str:
    return NAV_ICONS.get(key, "•")


def nav_label(key: str, label: str, *, compact: bool, badge: str = "") -> str:
    """Sidebar item text: icon-only in activity-bar mode, badge appended."""
    icon = nav_icon(key)
    if compact:
        return icon + (f" {badge}" if badge else "")
    text = f"{icon}  {label}"
    return text + (f"  · {badge}" if badge else "")


def filter_titles(titles, query: str) -> list[str]:
    """Case-insensitive substring filter for the chat session list."""
    needle = (query or "").strip().lower()
    items = [str(x) for x in (titles or [])]
    if not needle:
        return items
    return [x for x in items if needle in x.lower()]


def tooltip_text(label: str, hotkey: str = "") -> str:
    """Tooltip body: action name plus its hotkey when it has one."""
    return f"{label} ({hotkey})" if hotkey else label


def status_badges(*, provider: str = "", model: str = "", training: str = "",
                  tokens_today: int = 0, budget_usd: float = 0.0) -> list[str]:
    """Status-bar badge texts (VS Code style, right side, click → page)."""
    badges = []
    if model:
        badges.append(f"🤖 {provider + ' · ' if provider else ''}{model}")
    else:
        badges.append(t(t('🤖 модель не выбрана')))
    if training:
        badges.append(f"🏋 {training}")
    if tokens_today:
        text = t(t('🎟 {tokens_today} ток.')).format(tokens_today=tokens_today)
        if budget_usd:
            text += f" / ${budget_usd:.2f}"
        badges.append(text)
    return badges


def primary_action(key: str) -> tuple[str, str] | None:
    return PRIMARY_ACTIONS.get(key)
