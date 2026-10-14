"""Problems panel: errors from training logs/metrics with jump-to-code."""
from __future__ import annotations
from .i18n import t

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .metrics import parse_log
from .problems import MAX_PROBLEMS, parse_problems
from .ui_common import C, F_SMALL


class ProblemsPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["panel"])
        self.app = app
        self._items: list[dict] = []
        self.file_items: list[dict] = []  # from the editor's linter
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=C["panel"])
        bar.pack(fill="x", padx=8, pady=(6, 4))
        self.count_var = tk.StringVar(value=t('ПРОБЛЕМЫ'))
        tk.Label(bar, textvariable=self.count_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left")
        ttk.Button(bar, text=t('Обновить'), command=self.refresh).pack(side="left",
                                                                   padx=8)
        ttk.Button(bar, text=t('Наставнику'),
                   command=self.send_to_mentor).pack(side="left", padx=4)
        ttk.Button(bar, text=t('Очистить'),
                   command=self.clear).pack(side="left", padx=4)
        self.status_var = tk.StringVar(value=t('Ошибки из логов обучения — двойной клик открывает код.'))
        tk.Label(bar, textvariable=self.status_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left", padx=10)

        columns = ("severity", "message", "file")
        self.tree = ttk.Treeview(self, columns=columns, show="headings",
                                 height=6)
        for col, title, width in [
            ("severity", "!", 40), ("message", t('Проблема'), 520),
            ("file", t('Файл'), 240),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<Return>", lambda _e: self.open_selected())

    # ------------------------------------------------------------- handlers
    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._items = []
        self.file_items = []
        self.count_var.set(t('ПРОБЛЕМЫ (0)'))
        self.status_var.set(t('Очищено.'))

    def collect(self) -> list[dict]:
        problems = list(self.file_items)
        problems.extend(parse_problems(self.app.training.tail(60_000)))
        try:
            summary = parse_log(self.app.training.tail())
            for anomaly in summary.anomalies:
                problems.append({"severity": "warn", "message": anomaly,
                                 "path": "", "line": 0})
        except Exception:  # noqa: BLE001 - metrics parsing must not break UI
            pass
        return problems[:MAX_PROBLEMS]

    def refresh(self):
        self._items = self.collect()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for problem in self._items:
            mark = "×" if problem["severity"] == "error" else "!"
            location = problem["path"] + (f":{problem['line']}"
                                          if problem["line"] else "")
            self.tree.insert("", "end", values=(mark, problem["message"],
                                                location))
        self.count_var.set(t('ПРОБЛЕМЫ ({v1})').format(v1=len(self._items)))
        self.status_var.set(t('Найдено: ') + str(len(self._items)))
        editor = self.app.pages.get("editor")
        regen = getattr(editor, "_regen_gutter", None) if editor else None
        if callable(regen):
            regen()

    def open_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        children = list(self.tree.get_children())
        try:
            index = children.index(selection[0])
        except ValueError:
            return
        if not 0 <= index < len(self._items):
            return
        problem = self._items[index]
        if not problem["path"]:
            messagebox.showinfo(t('Проблемы'),
                                t('Для этой проблемы нет привязки к файлу.'),
                                parent=self)
            return
        root = self.app.workspace_root()
        path = Path(problem["path"])
        if root is not None and not path.is_absolute():
            path = root / path
        if not path.exists():
            messagebox.showinfo(t('Проблемы'), t('Файл не найден: {path}').format(path=path),
                                parent=self)
            return
        self.app.show_page("editor")
        self.app.pages["editor"].open_file(path, line=problem["line"] or None)

    def send_to_mentor(self):
        if not self._items:
            self.refresh()
        if not self._items:
            self.status_var.set(t('Проблем не найдено.'))
            return
        lines = [f"- [{p['severity']}] {p['message']}"
                 + (f" ({p['path']}:{p['line']})" if p["path"] else "")
                 for p in self._items[:30]]
        prompt = (t('Разбери эти проблемы из лога обучения, найди причины и предложи исправления:\n\n') + "\n".join(lines))
        self.app.show_page("chat")
        self.app.pages["chat"].send_preset(prompt)
