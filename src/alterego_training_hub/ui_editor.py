"""Code editor page: file tree + multi-tab editor (IDE-style) + mentor actions."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .templates import TemplateError, create_project, list_templates
from .ui_common import C, F_BASE, F_MONO, F_SMALL, Collapsible, card, page_header

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules",
                ".mypy_cache", ".pytest_cache", "checkpoints"}
MAX_TREE_FILES = 600
MAX_FILE_BYTES = 500_000
MAX_TABS = 20


def list_workspace_files(root: Path, limit: int = MAX_TREE_FILES) -> list[Path]:
    """Workspace files for the tree and the quick-open palette."""
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= limit:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


class EditorPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._tabs: list[dict] = []   # {"path": Path, "text": str, "modified": bool}
        self._active: int | None = None
        self._tab_widgets: list[tk.Label] = []
        self._current_path: Path | None = None
        self._build()

    def _build(self):
        header = page_header(
            self,
            "Редактор кода",
            "Файлы рабочей папки: просмотр, правка и разбор кода с наставником. "
            "Файлы открываются во вкладках; Ctrl+P — быстрое открытие.",
        )
        header.pack(fill="x", padx=24, pady=(20, 10))

        # Project scaffolding bar (collapsible)
        scaffold_section = Collapsible(self, "Новый проект из шаблона")
        scaffold_section.pack(fill="x", padx=24, pady=(0, 10))
        scaffold = scaffold_section.body
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

        # Editor card with tab bar
        right = card(body, "Редактор")
        right.pack(side="left", fill="both", expand=True)
        self.tab_bar = tk.Frame(right, bg=C["panel"])
        self.tab_bar.pack(fill="x")
        bar = tk.Frame(right, bg=C["panel"])
        bar.pack(fill="x", pady=(4, 6))
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
        self.editor.bind("<Control-w>", lambda _e: (self.close_tab(), "break")[1])
        self.editor.bind("<Control-Tab>", lambda _e: (self.next_tab(), "break")[1])
        self.editor.bind("<<Modified>>", self._on_modified)
        self.editor.bind("<KeyRelease>", lambda _e: self._update_cursor())
        self.editor.bind("<ButtonRelease-1>", lambda _e: self._update_cursor())
        self.status_var = tk.StringVar(value="")
        bottom = tk.Frame(right, bg=C["panel"])
        bottom.pack(fill="x", pady=(4, 0))
        tk.Label(bottom, textvariable=self.status_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left")
        self.cursor_var = tk.StringVar(value="")
        tk.Label(bottom, textvariable=self.cursor_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="right")

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
        for path in list_workspace_files(root):
            self.tree.insert("", "end", iid=str(path),
                             text=str(path.relative_to(root)))

    def open_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        self.open_file(Path(selection[0]))

    # --------------------------------------------------------------- tabs
    def _render_tabs(self):
        for widget in self._tab_widgets:
            widget.destroy()
        self._tab_widgets = []
        for index, tab in enumerate(self._tabs):
            mark = "• " if tab.get("modified") else ""
            label = tk.Label(
                self.tab_bar,
                text=f" {mark}{tab['path'].name}  ✕ ",
                font=F_SMALL, padx=8, pady=4, cursor="hand2",
                bg=C["accent"] if index == self._active else C["panel_alt"],
                fg="#ffffff" if index == self._active else C["text"],
            )
            label.pack(side="left", padx=(0, 2), pady=2)
            label.bind("<Button-1>",
                       lambda _e, i=index: self._select_tab(i))
            label.bind("<Button-2>",
                       lambda _e, i=index: self.close_tab(i))
            self._tab_widgets.append(label)

    def _stash_buffer(self):
        if self._active is not None and 0 <= self._active < len(self._tabs):
            self._tabs[self._active]["text"] = self.editor.get("1.0", "end-1c")

    def _select_tab(self, index: int):
        if not 0 <= index < len(self._tabs):
            return
        self._stash_buffer()
        tab = self._tabs[index]
        self._active = index
        self._current_path = tab["path"]
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", tab.get("text", ""))
        root = self.app.workspace_root()
        try:
            shown = tab["path"].relative_to(root) if root else tab["path"]
        except ValueError:
            shown = tab["path"]
        self.file_var.set(str(shown))
        self._render_tabs()
        self._update_cursor()

    def open_file(self, path: Path, line: int | None = None):
        path = Path(path)
        for index, tab in enumerate(self._tabs):
            if tab["path"] == path:
                self._select_tab(index)
                if line:
                    self.open_at(line)
                return
        try:
            raw = path.read_bytes()
        except OSError as exc:
            messagebox.showerror("Редактор", str(exc), parent=self)
            return
        if len(raw) > MAX_FILE_BYTES:
            messagebox.showerror("Редактор", "Файл слишком большой для редактора.",
                                 parent=self)
            return
        if len(self._tabs) >= MAX_TABS:
            self.close_tab(0)
        text = raw.decode("utf-8", errors="replace")
        self._tabs.append({"path": path, "text": text, "modified": False})
        self._select_tab(len(self._tabs) - 1)
        self.status_var.set(f"открыто {time.strftime('%H:%M:%S')} · {len(raw)} байт")
        if line:
            self.open_at(line)

    def open_at(self, line: int):
        try:
            self.editor.mark_set("insert", f"{int(line)}.0")
            self.editor.see(f"{int(line)}.0")
            self._update_cursor()
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    def close_tab(self, index: int | None = None):
        if not self._tabs:
            return
        index = self._active if index is None else index
        if index is None or not 0 <= index < len(self._tabs):
            return
        tab = self._tabs[index]
        if tab.get("modified") and not messagebox.askyesno(
                "Закрыть вкладку",
                f"«{tab['path'].name}» изменён. Закрыть без сохранения?",
                parent=self):
            return
        del self._tabs[index]
        self._active = None
        if self._tabs:
            self._select_tab(min(index, len(self._tabs) - 1))
        else:
            self._current_path = None
            self.editor.delete("1.0", "end")
            self.file_var.set("файл не открыт")
            self._render_tabs()

    def next_tab(self):
        if self._tabs:
            self._select_tab(((self._active or 0) + 1) % len(self._tabs))

    def _on_modified(self, _event=None):
        try:
            if self.editor.edit_modified() and self._active is not None:
                self._tabs[self._active]["modified"] = True
                self.editor.edit_modified(False)
                self._render_tabs()
        except Exception:  # noqa: BLE001 - fake widgets / shutdown
            pass

    def _update_cursor(self):
        try:
            index = str(self.editor.index("insert"))
            line, col = index.split(".", 1)
            self.cursor_var.set(f"Стр {line}, кол {int(col) + 1}")
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    def reload_file(self):
        if self._current_path is None:
            return
        path = self._current_path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror("Редактор", str(exc), parent=self)
            return
        if self._active is not None and 0 <= self._active < len(self._tabs):
            self._tabs[self._active]["text"] = text
            self._tabs[self._active]["modified"] = False
            self._select_tab(self._active)
        self.status_var.set(f"перечитано {time.strftime('%H:%M:%S')}")

    def save_file(self):
        if self._active is None or not self._tabs:
            messagebox.showinfo("Редактор", "Сначала откройте файл.", parent=self)
            return
        tab = self._tabs[self._active]
        content = self.editor.get("1.0", "end-1c")
        try:
            tab["path"].write_text(content, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Редактор", str(exc), parent=self)
            return
        tab["text"] = content
        tab["modified"] = False
        self._render_tabs()
        self.app.activity.log("file_edit", f"Сохранён файл {tab['path'].name}")
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
