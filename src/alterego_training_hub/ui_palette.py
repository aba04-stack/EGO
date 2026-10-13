"""Command palette and quick file open — the Ctrl+P / Ctrl+Shift+P experience."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from .ui_common import C, F_BASE, F_MONO
from .ui_editor import list_workspace_files

MAX_ITEMS = 400


def _fuzzy(query: str, label: str) -> bool:
    """Every whitespace-separated token of the query must appear in the label."""
    query = query.strip().lower()
    if not query:
        return True
    target = label.lower()
    return all(token in target for token in query.split())


class CommandPalette(tk.Toplevel):
    """Modal list with a filter box: commands or workspace files."""

    def __init__(self, app, mode: str = "commands"):
        super().__init__(app)
        self.app = app
        self.mode = mode
        self._items: list[tuple[str, Callable[[], Any] | Path]] = []
        self._filtered: list[int] = []
        title = "Быстрое открытие (Ctrl+P)" if mode == "files" else \
            "Палитра команд (Ctrl+Shift+P)"
        try:
            self.title(title)
            self.transient(app)
            self.geometry("680x420")
            self.grab_set()
        except Exception:  # noqa: BLE001 - window manager quirks
            pass
        self.configure(bg=C["bg"])

        tk.Label(self, text=title, bg=C["bg"], fg=C["muted"], font=F_BASE,
                 anchor="w", padx=12, pady=(10, 2)).pack(fill="x")
        self.query = tk.Entry(self, bd=1, relief="solid", font=F_MONO)
        self.query.pack(fill="x", padx=12, pady=6)
        self.listbox = tk.Listbox(self, bd=1, relief="solid", font=F_MONO,
                                  activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.query.bind("<KeyRelease>", lambda _e: self.refresh())
        self.query.bind("<Return>", lambda _e: self.run_selected())
        self.query.bind("<Down>", lambda _e: self._move(1))
        self.query.bind("<Up>", lambda _e: self._move(-1))
        self.listbox.bind("<Double-1>", lambda _e: self.run_selected())
        self.bind("<Escape>", lambda _e: self.close())

        self._build_items()
        self.refresh()
        try:
            self.query.focus_set()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- items
    def _build_items(self):
        app = self.app
        if self.mode == "files":
            root = app.workspace_root()
            if root is not None:
                for path in list_workspace_files(root, limit=MAX_ITEMS):
                    try:
                        label = str(path.relative_to(root))
                    except ValueError:
                        label = str(path)
                    self._items.append((label, path))
            else:
                self._items.append(("Рабочая папка не выбрана", None))
            return

        commands: list[tuple[str, Callable[[], Any]]] = [
            ("Перейти: Редактор кода", lambda: app.show_page("editor")),
            ("Перейти: Рабочая папка", lambda: app.show_page("workspace")),
            ("Перейти: Поиск по проекту", lambda: app.show_page("search")),
            ("Перейти: Модели", lambda: app.show_page("models")),
            ("Перейти: Датасеты", lambda: app.show_page("datasets")),
            ("Перейти: Модель и прогресс", lambda: app.show_page("model")),
            ("Перейти: Playground", lambda: app.show_page("playground")),
            ("Перейти: Обучение", lambda: app.show_page("training")),
            ("Перейти: Внешние GPU", lambda: app.show_page("gpu")),
            ("Перейти: Серверы", lambda: app.show_page("servers")),
            ("Перейти: Коннекторы", lambda: app.show_page("connectors")),
            ("Перейти: Настройки", lambda: app.show_page("settings")),
            ("Чат: фокус в поле ввода", lambda: app.show_page("chat")),
            ("Панель: терминал / проблемы", lambda: app.show_bottom("terminal")),
            ("Проблемы: открыть и обновить",
             lambda: app.show_bottom("problems")),
            ("Панель: свернуть/развернуть (Ctrl+J)", app.toggle_bottom),
            ("Страница: обновить (F5)", app.refresh_current),
            ("Редактор: сохранить файл", lambda: app.pages["editor"].save_file()),
            ("Редактор: закрыть вкладку", lambda: app.pages["editor"].close_tab()),
            ("Диагностика: запустить проверку",
             lambda: app.pages["settings"].run_check()),
            ("Обучение: запустить", lambda: app.pages["training"].start_training()),
            ("Обучение: остановить", lambda: app.pages["training"].stop_training()),
        ]
        self._items.extend(commands)

    def refresh(self):
        try:
            query = self.query.get()
        except Exception:  # noqa: BLE001
            query = ""
        self.listbox.delete(0, "end")
        self._filtered = []
        for index, (label, _target) in enumerate(self._items):
            if _fuzzy(query, label):
                self.listbox.insert("end", label)
                self._filtered.append(index)
        if self._filtered:
            try:
                self.listbox.selection_set(0)
                self.listbox.activate(0)
            except Exception:  # noqa: BLE001
                pass

    def _move(self, step: int):
        try:
            size = self.listbox.size()
            if not size:
                return
            current = (self.listbox.curselection() or (0,))[0]
            self.listbox.selection_clear(0, "end")
            target = (current + step) % size
            self.listbox.selection_set(target)
            self.listbox.activate(target)
        except Exception:  # noqa: BLE001
            pass

    def run_selected(self):
        try:
            selection = self.listbox.curselection()
        except Exception:  # noqa: BLE001
            selection = ()
        position = selection[0] if selection else 0
        if not self._filtered or position >= len(self._filtered):
            self.close()
            return
        _label, target = self._items[self._filtered[position]]
        self.close()
        if self.mode == "files":
            if isinstance(target, Path):
                self.app.show_page("editor")
                self.app.pages["editor"].open_file(target)
        elif callable(target):
            target()

    def close(self):
        try:
            self.destroy()
        except Exception:  # noqa: BLE001
            pass


def open_command_palette(app, mode: str = "commands") -> CommandPalette:
    return CommandPalette(app, mode)
