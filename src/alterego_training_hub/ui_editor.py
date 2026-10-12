"""Code editor page: browse, edit and discuss workspace files with the mentor."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .templates import TemplateError, create_project, list_templates
from .ui_common import C, F_BASE, F_MONO, F_SMALL, card, page_header

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules",
                ".mypy_cache", ".pytest_cache", "checkpoints"}
MAX_TREE_FILES = 600
MAX_FILE_BYTES = 500_000


class EditorPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._current_path: Path | None = None
        self._build()

    def _build(self):
        header = page_header(
            self,
            "Редактор кода",
            "Файлы рабочей папки: просмотр, правка и разбор кода с наставником. "
            "Создайте новый проект из шаблона, чтобы начать обучение сразу.",
        )
        header.pack(fill="x", padx=24, pady=(20, 10))

        # Project scaffolding bar
        scaffold = card(self)
        scaffold.pack(fill="x", padx=24, pady=(0, 10))
        row = tk.Frame(scaffold, bg=C["panel"])
        row.pack(fill="x")
        tk.Label(row, text="Новый проект", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.project_var = tk.StringVar()
        tk.Entry(row, textvariable=self.project_var, width=22, bd=1,
                 relief="solid", font=F_BASE).pack(side="left", padx=(0, 8))
        templates = [f"{item.id} — {item.title}" for item in list_templates()]
        self.template_var = tk.StringVar(value=templates[0] if templates else "")
        ttk.Combobox(row, textvariable=self.template_var, values=templates,
                     state="readonly", width=42).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Создать проект", style="Accent.TButton",
                   command=self.create_project).pack(side="left")
        self.project_hint = tk.StringVar(value="")
        tk.Label(row, textvariable=self.project_hint, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left", padx=12)

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(0, 14))

        # File tree
        left = card(body, "Файлы")
        left.pack(side="left", fill="y", padx=(0, 10))
        self.tree = ttk.Treeview(left, columns=("path",), show="tree",
                                 height=22, selectmode="browse")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        tree_btns = tk.Frame(left, bg=C["panel"])
        tree_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(tree_btns, text="Обновить", command=self.refresh_tree).pack(
            side="left")
        ttk.Button(tree_btns, text="Открыть", command=self.open_selected).pack(
            side="left", padx=6)

        # Editor
        right = card(body, "Редактор")
        right.pack(side="left", fill="both", expand=True)
        bar = tk.Frame(right, bg=C["panel"])
        bar.pack(fill="x", pady=(0, 6))
        self.file_var = tk.StringVar(value="файл не открыт")
        tk.Label(bar, textvariable=self.file_var, bg=C["panel"], fg=C["muted"],
                 font=F_MONO).pack(side="left")
        ttk.Button(bar, text="Сохранить", style="Accent.TButton",
                   command=self.save_file).pack(side="right")
        ttk.Button(bar, text="Перечитать",
                   command=self.reload_file).pack(side="right", padx=6)
        ttk.Button(bar, text="Обсудить с наставником",
                   command=self.send_to_mentor).pack(side="right", padx=6)

        self.editor = tk.Text(right, wrap="none", font=F_MONO, bd=1,
                              relief="solid", undo=True)
        self.editor.pack(fill="both", expand=True)
        self.editor.bind("<Control-s>", lambda _e: (self.save_file(), "break")[1])
        self.status_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self.status_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------- projects
    def on_show(self):
        self.refresh_tree()

    def create_project(self):
        root = self.app.workspace_root()
        if root is None:
            messagebox.showerror("Проект", "Сначала выберите рабочую папку.",
                                 parent=self)
            self.app.show_page("workspace")
            return
        name = self.project_var.get().strip()
        template_id = self.template_var.get().split(" — ")[0].strip()
        try:
            created = create_project(root, name, template_id)
        except TemplateError as exc:
            messagebox.showerror("Проект", str(exc), parent=self)
            return
        self.app.activity.log("system", f"Создан проект «{name}» ({template_id})",
                              files=created)
        self.project_var.set("")
        self.project_hint.set(f"Создано файлов: {len(created)}")
        self.refresh_tree()
        self.app.set_status(f"Проект {name} создан")

    # -------------------------------------------------------------- files
    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        root = self.app.workspace_root()
        if root is None:
            return
        count = 0
        for path in sorted(root.rglob("*")):
            if count >= MAX_TREE_FILES:
                break
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            self.tree.insert("", "end", iid=str(path), text=str(rel))
            count += 1

    def open_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        self.open_file(Path(selection[0]))

    def open_file(self, path: Path):
        try:
            raw = path.read_bytes()
        except OSError as exc:
            messagebox.showerror("Редактор", str(exc), parent=self)
            return
        if len(raw) > MAX_FILE_BYTES:
            messagebox.showerror("Редактор", "Файл слишком большой для редактора.",
                                 parent=self)
            return
        self._current_path = path
        text = raw.decode("utf-8", errors="replace")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        root = self.app.workspace_root()
        try:
            shown = path.relative_to(root) if root else path
        except ValueError:
            shown = path
        self.file_var.set(str(shown))
        self.status_var.set(f"открыто {time.strftime('%H:%M:%S')} · {len(raw)} байт")

    def reload_file(self):
        if self._current_path is not None:
            self.open_file(self._current_path)

    def save_file(self):
        if self._current_path is None:
            messagebox.showinfo("Редактор", "Сначала откройте файл.", parent=self)
            return
        content = self.editor.get("1.0", "end-1c")
        try:
            self._current_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Редактор", str(exc), parent=self)
            return
        self.app.activity.log("file_edit", f"Сохранён файл {self._current_path.name}")
        self.status_var.set(f"сохранено {time.strftime('%H:%M:%S')}")
        self.app.set_status("Файл сохранён")

    def send_to_mentor(self):
        if self._current_path is None:
            messagebox.showinfo("Редактор", "Сначала откройте файл.", parent=self)
            return
        content = self.editor.get("1.0", "end-1c")
        if len(content) > 120_000:
            content = content[:120_000] + "\n…[файл обрезан]"
        prompt = (
            f"Разбери этот код, найди ошибки и предложи улучшения.\n\n"
            f"Файл: {self.file_var.get()}\n```\n{content}\n```"
        )
        self.app.show_page("chat")
        self.app.pages["chat"].send_preset(prompt)
