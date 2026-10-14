"""Workspace layouts: named presets plus save/restore of the current layout.

A layout captures the visible page, the bottom panel state and the window
geometry — enough to jump between «coding», «training» and «analytics»
arrangements without dragging panels by hand.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


class LayoutError(RuntimeError):
    """Layout input error safe to display."""


VALID_PAGES = {"editor", "workspace", "search", "models", "datasets", "model",
               "playground", "training", "gpu", "servers", "connectors",
               "settings", "chat"}


@dataclass
class LayoutState:
    page: str = "editor"
    bottom_visible: bool = True
    bottom_view: str = "terminal"  # terminal | problems | git
    geometry: str = ""

    def validate(self) -> None:
        if self.page not in VALID_PAGES:
            raise LayoutError(f"Неизвестная страница: {self.page}")
        if self.bottom_view not in {"terminal", "problems", "git"}:
            raise LayoutError(f"Неизвестная нижняя панель: {self.bottom_view}")


NAMED_LAYOUTS: dict[str, LayoutState] = {
    "code": LayoutState(page="editor", bottom_visible=True,
                        bottom_view="terminal"),
    "training": LayoutState(page="training", bottom_visible=True,
                            bottom_view="problems"),
    "analytics": LayoutState(page="model", bottom_visible=False),
    "chat": LayoutState(page="chat", bottom_visible=True, bottom_view="git"),
}


def layout_names() -> list[str]:
    return list(NAMED_LAYOUTS)


def layout_info(name: str) -> LayoutState:
    state = NAMED_LAYOUTS.get(str(name or "").strip().lower())
    if state is None:
        raise LayoutError(f"Раскладка: одна из {layout_names()}.")
    return LayoutState(**asdict(state))


def save_layout(path: str | Path, state: LayoutState) -> Path:
    state.validate()
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return file


def load_layout(path: str | Path) -> LayoutState:
    file = Path(path)
    if not file.is_file():
        raise LayoutError(f"Файл раскладки не найден: {file}")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LayoutError(f"Некорректный JSON раскладки: {exc}") from None
    if not isinstance(raw, dict):
        raise LayoutError("Файл раскладки должен содержать объект.")
    state = LayoutState(**{
        key: value for key, value in raw.items()
        if key in LayoutState.__dataclass_fields__})
    state.validate()
    return state
