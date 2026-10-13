"""Code editor page: tree + tabbed IDE editor with gutter, find/replace, bookmarks."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .finding import iter_matches, next_match_index, replace_all
from .formatter import format_source
from .lint import check_source
from .minimap import minimap_bars
from .pairing import (
    PAIRS,
    auto_close_decision,
    backspace_decision,
    bracket_for_cursor,
    find_matching_bracket,
)
from .pathutil import PathSafetyError, safe_child_path
from .syntax import configure_tags, detect_language, highlight
from .templates import TemplateError, create_project, list_templates
from .ui_common import C, F_BASE, F_MONO, F_SMALL, Collapsible, card, page_header
from .ui_completion import CompletionPopup

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules",
                ".mypy_cache", ".pytest_cache", "checkpoints"}
MAX_TREE_FILES = 600
MAX_FILE_BYTES = 500_000
MAX_TABS = 20
MARK_PROBLEM = "●"
MARK_BOOKMARK = "★"


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
        self._tabs: list[dict] = []   # {"path", "text", "modified", "bookmarks"}
        self._active: int | None = None
        self._tab_widgets: list[tk.Label] = []
        self._current_path: Path | None = None
        self._language = "generic"
        self._highlight_after: str | None = None
        self._matches: list[tuple[int, int]] = []
        self._match_index: int | None = None
        self._zoom: int = 0
        self._build()
        self.completion = CompletionPopup(self)

    def _build(self):
        header = page_header(
            self,
            "Редактор кода",
            "Файлы рабочей папки: просмотр, правка и разбор кода с наставником. "
            "Ctrl+P — быстрое открытие, Ctrl+F — поиск, Ctrl+F2 — закладка.",
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
        file_ops = tk.Frame(left, bg=C["panel"])
        file_ops.pack(fill="x", pady=(4, 0))
        self.new_name_var = tk.StringVar()
        tk.Entry(file_ops, textvariable=self.new_name_var, width=16, bd=1,
                 relief="solid", font=F_BASE).pack(side="left")
        ttk.Button(file_ops, text="+ Файл",
                   command=self.create_file).pack(side="left", padx=4)
        ttk.Button(file_ops, text="Переименовать",
                   command=self.rename_selected).pack(side="left")
        ttk.Button(file_ops, text="Удалить",
                   command=self.delete_selected).pack(side="left", padx=4)

        # Editor card: tab bar + find bar + gutter + text
        right = card(body, "Редактор")
        right.pack(side="left", fill="both", expand=True)
        self.tab_bar = tk.Frame(right, bg=C["panel"])
        self.tab_bar.pack(fill="x")

        # Find / replace bar (hidden until Ctrl+F)
        self.find_bar = tk.Frame(right, bg=C["panel_alt"])
        self.find_visible = False
        find_row = tk.Frame(self.find_bar, bg=C["panel_alt"])
        find_row.pack(fill="x", padx=2, pady=2)
        tk.Label(find_row, text="Найти", bg=C["panel_alt"], font=F_SMALL).pack(
            side="left", padx=(6, 4))
        self.find_var = tk.StringVar()
        self.find_entry = tk.Entry(find_row, textvariable=self.find_var, width=28,
                                   bd=1, relief="solid", font=F_MONO)
        self.find_entry.pack(side="left", padx=(0, 6))
        self.find_entry.bind("<Return>", lambda _e: (self.find_next(1), "break")[1])
        self.find_entry.bind("<Shift-Return>",
                             lambda _e: (self.find_next(-1), "break")[1])
        self.find_entry.bind("<Escape>", lambda _e: (self.close_find(), "break")[1])
        ttk.Button(find_row, text="▲", width=3,
                   command=lambda: self.find_next(-1)).pack(side="left")
        ttk.Button(find_row, text="▼", width=3,
                   command=lambda: self.find_next(1)).pack(side="left", padx=(2, 6))
        self.match_case = tk.BooleanVar(value=False)
        tk.Checkbutton(find_row, text="Aa", variable=self.match_case,
                       bg=C["panel_alt"], font=F_SMALL,
                       command=self._refresh_matches).pack(side="left", padx=(0, 6))
        self.find_status = tk.StringVar(value="")
        tk.Label(find_row, textvariable=self.find_status, bg=C["panel_alt"],
                 fg=C["muted"], font=F_SMALL, width=14).pack(side="left")

        replace_row = tk.Frame(self.find_bar, bg=C["panel_alt"])
        tk.Label(replace_row, text="Заменить", bg=C["panel_alt"],
                 font=F_SMALL).pack(side="left", padx=(6, 4))
        self.replace_var = tk.StringVar()
        self.replace_entry = tk.Entry(replace_row, textvariable=self.replace_var,
                                      width=28, bd=1, relief="solid", font=F_MONO)
        self.replace_entry.pack(side="left", padx=(0, 6))
        self.replace_entry.bind("<Escape>",
                                lambda _e: (self.close_find(), "break")[1])
        ttk.Button(replace_row, text="Заменить",
                   command=self.replace_current).pack(side="left", padx=(0, 4))
        ttk.Button(replace_row, text="Всё",
                   command=self.replace_all_in_file).pack(side="left", padx=(0, 4))
        ttk.Button(find_row, text="✕", width=3,
                   command=self.close_find).pack(side="right", padx=6)

        # Go-to-line bar (hidden until Ctrl+G)
        self.goto_bar = tk.Frame(right, bg=C["panel_alt"])
        self.goto_visible = False
        goto_row = tk.Frame(self.goto_bar, bg=C["panel_alt"])
        goto_row.pack(fill="x", padx=2, pady=2)
        tk.Label(goto_row, text="Строка", bg=C["panel_alt"],
                 font=F_SMALL).pack(side="left", padx=(6, 4))
        self.goto_var = tk.StringVar()
        self.goto_entry = tk.Entry(goto_row, textvariable=self.goto_var,
                                   width=10, bd=1, relief="solid", font=F_MONO)
        self.goto_entry.pack(side="left", padx=(0, 6))
        self.goto_entry.bind("<Return>",
                             lambda _e: (self.goto_line_jump(), "break")[1])
        self.goto_entry.bind("<Escape>",
                             lambda _e: (self.close_goto_line(), "break")[1])
        ttk.Button(goto_row, text="Перейти",
                   command=self.goto_line_jump).pack(side="left", padx=(0, 4))
        ttk.Button(goto_row, text="✕", width=3,
                   command=self.close_goto_line).pack(side="right", padx=6)

        bar = tk.Frame(right, bg=C["panel"])
        bar.pack(fill="x", pady=(4, 6))
        self.file_var = tk.StringVar(value="файл не открыт")
        tk.Label(bar, textvariable=self.file_var, bg=C["panel"], fg=C["muted"],
                 font=F_MONO).pack(side="left")
        self.format_on_save = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="формат при сохранении",
                       variable=self.format_on_save, bg=C["panel"],
                       font=F_SMALL).pack(side="left", padx=(10, 0))
        self.lint_on_save = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="линт при сохранении",
                       variable=self.lint_on_save, bg=C["panel"],
                       font=F_SMALL).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Сохранить", style="Accent.TButton",
                   command=self.save_file).pack(side="right")
        ttk.Button(bar, text="Перечитать",
                   command=self.reload_file).pack(side="right", padx=6)
        ttk.Button(bar, text="Формат",
                   command=self.format_file).pack(side="right", padx=6)
        ttk.Button(bar, text="Проверить",
                   command=self.run_lint).pack(side="right", padx=6)
        ttk.Button(bar, text="Обсудить с наставником",
                   command=self.send_to_mentor).pack(side="right", padx=6)

        # Code area: gutter + editor + minimap + scrollbar
        code_wrap = tk.Frame(right, bg=C["code_bg"])
        code_wrap.pack(fill="both", expand=True)
        self.gutter = tk.Text(code_wrap, width=7, wrap="none", font=F_MONO,
                              bd=0, padx=2, pady=6, state="disabled",
                              bg=C["panel_alt"], fg=C["muted"],
                              selectbackground=C["panel_alt"], cursor="hand2")
        self.gutter.pack(side="left", fill="y")
        self.gutter.bind("<Button-1>", self._on_gutter_click)
        self.editor = tk.Text(code_wrap, wrap="none", font=F_MONO, bd=0,
                              undo=True, padx=8, pady=6,
                              bg=C["code_bg"], fg=C["code_fg"],
                              insertbackground=C["code_fg"],
                              selectbackground=C["accent"],
                              selectforeground="#ffffff")
        self.editor.pack(side="left", fill="both", expand=True)
        self.minimap = tk.Canvas(code_wrap, width=64, bd=0,
                                 highlightthickness=0, bg=C["panel_alt"],
                                 cursor="hand2")
        self.minimap.pack(side="right", fill="y")
        self.minimap.bind("<Button-1>", self._on_minimap_click)
        scroll = ttk.Scrollbar(code_wrap, command=self.editor.yview)
        scroll.pack(side="right", fill="y")
        self.editor.configure(yscrollcommand=lambda a, b: self._sync_scroll(a, b))
        configure_tags(self.editor)
        self.editor.tag_configure("find_match", background="#8a6d1f")
        self.editor.tag_configure("find_current", background=C["accent"],
                                  foreground="#ffffff")
        self.editor.tag_configure("line_problem", background="#3f1d24")
        self.editor.tag_configure("bracket_match", background="#2f4f6f")
        self.editor.bind("<Control-s>", lambda _e: (self.save_file(), "break")[1])
        self.editor.bind("<Control-w>", lambda _e: (self.close_tab(), "break")[1])
        self.editor.bind("<Control-Tab>", lambda _e: (self.next_tab(), "break")[1])
        self.editor.bind("<Control-g>",
                         lambda _e: (self.open_goto_line(), "break")[1])
        self.editor.bind("<Control-plus>",
                         lambda _e: (self.zoom_in(), "break")[1])
        self.editor.bind("<Control-equal>",
                         lambda _e: (self.zoom_in(), "break")[1])
        self.editor.bind("<Control-KP_Add>",
                         lambda _e: (self.zoom_in(), "break")[1])
        self.editor.bind("<Control-minus>",
                         lambda _e: (self.zoom_out(), "break")[1])
        self.editor.bind("<Control-KP_Subtract>",
                         lambda _e: (self.zoom_out(), "break")[1])
        for char in ("(", "[", "{", '"', "'", ")", "]", "}"):
            self.editor.bind(
                char, lambda _e, ch=char: self._on_auto_char(ch, _e))
        self.editor.bind("<BackSpace>", self._on_backspace)
        self.editor.bind("<<Modified>>", self._on_modified)
        self.editor.bind("<KeyRelease>", self._on_key_release)
        self.editor.bind("<ButtonRelease-1>", self._on_click)
        self.editor.bind("<Tab>", self._on_tab_key)
        self.editor.bind("<Escape>", self._on_escape)
        self.editor.bind("<Return>", self._on_return_key)
        self.editor.bind("<Up>", self._on_up_key)
        self.editor.bind("<Down>", self._on_down_key)
        self.editor.bind("<Control-f>", lambda _e: (self.open_find(), "break")[1])
        self.editor.bind("<Control-h>",
                         lambda _e: (self.open_find(replace=True), "break")[1])
        self.editor.bind("<F3>", lambda _e: (self.find_next(1), "break")[1])
        self.editor.bind("<Shift-F3>", lambda _e: (self.find_next(-1), "break")[1])
        self.editor.bind("<Control-F2>", lambda _e: (self.toggle_bookmark(),
                                                     "break")[1])
        self.editor.bind("<F2>", lambda _e: (self.goto_bookmark(1), "break")[1])
        self.editor.bind("<Shift-F2>", lambda _e: (self.goto_bookmark(-1),
                                                   "break")[1])
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

    # -------------------------------------------------------- file actions
    def create_file(self):
        root = self.app.workspace_root()
        if root is None:
            messagebox.showerror("Файлы", "Сначала выберите рабочую папку.",
                                 parent=self)
            return
        try:
            target = safe_child_path(root, self.new_name_var.get())
        except PathSafetyError as exc:
            messagebox.showerror("Файлы", str(exc), parent=self)
            return
        if target.exists():
            messagebox.showerror("Файлы", "Файл уже существует.", parent=self)
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Файлы", f"Не удалось создать файл: {exc}",
                                 parent=self)
            return
        self.new_name_var.set("")
        self.refresh_tree()
        self.open_file(target)
        self.status_var.set(f"создан файл {target.name}")

    def rename_selected(self):
        root = self.app.workspace_root()
        selection = self.tree.selection()
        if root is None or not selection:
            messagebox.showerror("Файлы", "Выберите файл в дереве.", parent=self)
            return
        old_path = Path(selection[0])
        if not old_path.is_file():
            messagebox.showerror("Файлы", "Переименовать можно только файл.",
                                 parent=self)
            return
        try:
            new_path = safe_child_path(root, self.new_name_var.get())
        except PathSafetyError as exc:
            messagebox.showerror("Файлы", str(exc), parent=self)
            return
        if new_path.exists():
            messagebox.showerror("Файлы", "Имя уже занято.", parent=self)
            return
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
        except OSError as exc:
            messagebox.showerror("Файлы", f"Не удалось переименовать: {exc}",
                                 parent=self)
            return
        for tab in self._tabs:
            if tab["path"] == old_path:
                tab["path"] = new_path
        if self._current_path == old_path:
            self._current_path = new_path
            self.file_var.set(str(new_path))
        self.new_name_var.set("")
        self.refresh_tree()
        self.status_var.set(f"переименовано в {new_path.name}")

    def delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showerror("Файлы", "Выберите файл в дереве.", parent=self)
            return
        path = Path(selection[0])
        if not path.is_file():
            messagebox.showerror("Файлы", "Удалить можно только файл.",
                                 parent=self)
            return
        if not messagebox.askyesno(
            "Удалить файл",
            f"Удалить {path.name}? Файл будет удалён безвозвратно.",
            parent=self,
        ):
            return
        for index in [i for i, tab in enumerate(self._tabs)
                      if tab["path"] == path]:
            self.close_tab(index)
        try:
            path.unlink()
        except OSError as exc:
            messagebox.showerror("Файлы", f"Не удалось удалить: {exc}",
                                 parent=self)
            return
        self.refresh_tree()
        self.status_var.set(f"удалён файл {path.name}")

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
        self._language = detect_language(tab["path"])
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
        self._apply_highlight()

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
        self._tabs.append({"path": path, "text": text, "modified": False,
                           "bookmarks": set()})
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

    # -------------------------------------------------------- go to line
    def open_goto_line(self):
        self.close_find()
        if not self.goto_visible:
            self.goto_bar.pack(fill="x")
            self.goto_visible = True
        self.goto_entry.focus_set()
        self.goto_entry.selection_range(0, "end")

    def close_goto_line(self):
        if self.goto_visible:
            self.goto_bar.pack_forget()
            self.goto_visible = False
        self.editor.focus_set()

    def goto_line_jump(self):
        raw = self.goto_var.get().strip()
        try:
            line = int(raw)
        except ValueError:
            line = 0
        total = self._line_count()
        if line >= 1:
            self.open_at(min(line, total))
            self.status_var.set(f"переход к строке {min(line, total)}")
        self.close_goto_line()

    # ------------------------------------------------- brackets & pairing
    def _cursor_line_col(self) -> tuple[str, int]:
        try:
            index = self.editor.index("insert")
            line, col = str(index).split(".")
            return self.editor.get(f"{line}.0", f"{line}.end"), int(col)
        except Exception:  # noqa: BLE001 - widget may be gone / fake
            return "", 0

    def _on_auto_char(self, char: str, _event=None):
        line, col = self._cursor_line_col()
        decision = auto_close_decision(line, col, char)
        if decision == "pair":
            try:
                self.editor.insert("insert", char + PAIRS[char])
                self.editor.mark_set("insert", "insert-1c")
                self._on_modified_force()
            except Exception:  # noqa: BLE001
                return None
            return "break"
        if decision == "skip":
            try:
                self.editor.mark_set("insert", "insert+1c")
            except Exception:  # noqa: BLE001
                return None
            return "break"
        return None

    def _on_backspace(self, _event=None):
        line, col = self._cursor_line_col()
        if backspace_decision(line, col) == 2:
            try:
                self.editor.delete("insert-2c", "insert")
                self._on_modified_force()
            except Exception:  # noqa: BLE001
                return None
            return "break"
        return None

    def _highlight_bracket(self):
        try:
            self.editor.tag_remove("bracket_match", "1.0", "end")
            offset = self.editor.count("1.0", "insert", "chars")
            if offset is None:
                return
            text = self.editor.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001 - widget may be gone / fake
            return
        index = bracket_for_cursor(text, int(offset))
        if index is None:
            return
        match = find_matching_bracket(text, index)
        if match is None:
            return
        for position in (index, match):
            self.editor.tag_add("bracket_match", f"1.0+{position}c",
                                f"1.0+{position + 1}c")

    # ------------------------------------------------------------- zoom
    def zoom_in(self):
        self._apply_zoom(1)

    def zoom_out(self):
        self._apply_zoom(-1)

    def _apply_zoom(self, step: int):
        self._zoom = max(-4, min(12, getattr(self, "_zoom", 0) + step))
        size = max(6, F_MONO[1] + self._zoom)
        font = (F_MONO[0], size)
        for widget in (self.editor, self.gutter):
            try:
                widget.configure(font=font)
            except Exception:  # noqa: BLE001
                pass
        self.status_var.set(f"масштаб шрифта: {size} пт")

    # ----------------------------------------------------------- minimap
    def _redraw_minimap(self):
        try:
            self.minimap.delete("all")
            text = self.editor.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001 - fake widgets
            return
        bars = minimap_bars(text)
        if not bars:
            return
        try:
            width = int(self.minimap.winfo_width() or 64)
            height = int(self.minimap.winfo_height() or 400)
        except Exception:  # noqa: BLE001
            width, height = 64, 400
        row_h = max(2, height // max(1, len(bars)))
        colors = {"code": "#6b7c93", "def": "#3b82f6", "head": "#8ab4f8",
                  "comment": "#4f7a4f", "blank": None}
        for index, bar in enumerate(bars):
            if bar["kind"] == "blank" or bar["width"] == 0:
                continue
            color = colors.get(bar["kind"], "#6b7c93")
            x0 = 4 + min(bar["indent"], 24)
            x1 = min(width - 4, x0 + max(2, bar["width"] // 2))
            y0 = index * row_h + 1
            self.minimap.create_rectangle(x0, y0, x1, y0 + max(1, row_h - 1),
                                          fill=color, outline="")

    def _on_minimap_click(self, event=None):
        try:
            y = int(getattr(event, "y", 0))
            height = int(self.minimap.winfo_height() or 0)
            if height <= 0:
                return
            total = self._line_count()
            self.open_at(1 + int(y / height * max(1, total - 1)))
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    # ------------------------------------------------- format and linting
    def format_file(self):
        if self._active is None or not self._tabs:
            messagebox.showinfo("Редактор", "Сначала откройте файл.",
                                parent=self)
            return
        text = self.editor.get("1.0", "end-1c")
        new_text, fixes = format_source(text)
        if not fixes:
            self.status_var.set("форматирование: изменений нет")
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", new_text)
        self._on_modified_force()
        self._schedule_highlight()
        self.status_var.set(f"форматировано: {fixes} исправлений")

    def run_lint(self):
        if self._active is None or not self._tabs:
            messagebox.showinfo("Редактор", "Сначала откройте файл.",
                                parent=self)
            return
        path = self._tabs[self._active]["path"]
        text = self.editor.get("1.0", "end-1c")
        rows = check_source(text, path=path.name,
                            language=detect_language(str(path)))
        problems = getattr(self.app, "problems", None)
        if problems is not None:
            problems.file_items = rows
            problems.refresh()
        errors = sum(1 for row in rows if row["severity"] == "error")
        if rows:
            self.status_var.set(
                f"линт: {errors} ошиб(ок), {len(rows) - errors} предупреждений")
        else:
            self.status_var.set("линт: проблем не найдено")

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
            self._regen_gutter()

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

    # ------------------------------------------------------- gutter / marks
    def _sync_scroll(self, first, _last):
        try:
            self.gutter.yview_moveto(first)
        except Exception:  # noqa: BLE001
            pass

    def _line_count(self) -> int:
        try:
            text = self.editor.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            return 0
        return text.count("\n") + 1 if text else 0

    def _problem_lines(self) -> set[int]:
        if self._current_path is None:
            return set()
        name = self._current_path.name
        lines: set[int] = set()
        panel = getattr(self.app, "problems", None)
        problems = getattr(panel, "_items", []) if panel is not None else []
        for problem in problems or []:
            path = str(problem.get("path") or "")
            if problem.get("line") and (path.endswith(name) or path == name):
                lines.add(int(problem["line"]))
        return lines

    def _regen_gutter(self):
        total = self._line_count()
        bookmarks: set[int] = set()
        if self._active is not None and 0 <= self._active < len(self._tabs):
            bookmarks = self._tabs[self._active].get("bookmarks", set())
        problems = self._problem_lines()
        try:
            self.gutter.configure(state="normal")
            self.gutter.delete("1.0", "end")
            for number in range(1, total + 1):
                mark = (MARK_PROBLEM if number in problems else
                        MARK_BOOKMARK if number in bookmarks else " ")
                self.gutter.insert("end", f"{number:>4} {mark}\n")
                if number in problems:
                    self.gutter.tag_add("line_problem",
                                        f"{number}.0", f"{number}.end")
            self.gutter.configure(state="disabled")
        except Exception:  # noqa: BLE001 - fake widgets
            pass

    def _on_gutter_click(self, event=None):
        try:
            index = self.gutter.index(f"@0,{event.y}")
            line = int(str(index).split(".", 1)[0])
        except Exception:  # noqa: BLE001 - fake widgets / bad coords
            return
        self.toggle_bookmark(line)

    # ---------------------------------------------------------- bookmarks
    def current_line(self) -> int:
        try:
            return int(str(self.editor.index("insert")).split(".", 1)[0])
        except Exception:  # noqa: BLE001
            return 1

    def toggle_bookmark(self, line: int | None = None):
        if self._active is None or not self._tabs:
            return
        line = line or self.current_line()
        marks: set[int] = self._tabs[self._active].setdefault("bookmarks", set())
        if line in marks:
            marks.discard(line)
        else:
            marks.add(line)
        self._regen_gutter()
        self.status_var.set(f"закладки: {len(marks)}")

    def goto_bookmark(self, direction: int = 1):
        if self._active is None or not self._tabs:
            return
        marks = sorted(self._tabs[self._active].get("bookmarks", set()))
        if not marks:
            self.status_var.set("закладок нет")
            return
        line = self.current_line()
        if direction >= 0:
            target = next((m for m in marks if m > line), marks[0])
        else:
            target = next((m for m in reversed(marks) if m < line), marks[-1])
        self.open_at(target)

    # ------------------------------------------------------ find / replace
    def open_find(self, replace: bool = False):
        self.find_visible = True
        self.find_bar.pack(fill="x", padx=2, pady=(0, 4))
        if replace:
            replace_row = self.replace_entry.master
            replace_row.pack(fill="x", padx=2, pady=(0, 2))
        self._refresh_matches()
        try:
            self.find_entry.focus_set()
            self.find_entry.selection_range(0, "end")
        except Exception:  # noqa: BLE001
            pass

    def close_find(self):
        self.find_visible = False
        try:
            self.find_bar.pack_forget()
        except Exception:  # noqa: BLE001
            pass
        self._clear_find_tags()
        self._matches = []
        self._match_index = None
        try:
            self.editor.focus_set()
        except Exception:  # noqa: BLE001
            pass

    def _clear_find_tags(self):
        for tag in ("find_match", "find_current"):
            try:
                self.editor.tag_remove(tag, "1.0", "end")
            except Exception:  # noqa: BLE001
                pass

    def _refresh_matches(self):
        self._clear_find_tags()
        query = self.find_var.get()
        try:
            text = self.editor.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            return
        self._matches = iter_matches(text, query,
                                     case_sensitive=bool(self.match_case.get()))
        for start, end in self._matches:
            try:
                self.editor.tag_add("find_match", f"1.0+{start}c",
                                    f"1.0+{end}c")
            except Exception:  # noqa: BLE001
                pass
        self._match_index = None
        self.find_status.set(f"{len(self._matches)} совпад." if query else "")

    def find_next(self, direction: int = 1):
        if not self.find_visible:
            self.open_find()
        self._refresh_matches()
        if not self._matches:
            self.find_status.set("нет совпадений" if self.find_var.get() else "")
            return
        try:
            cursor = self.editor.count("1.0", self.editor.index("insert"), "chars")
            if isinstance(cursor, (tuple, list)):
                cursor = cursor[0] if cursor else 0
            cursor = int(cursor or 0)
        except Exception:  # noqa: BLE001
            cursor = 0
        index = next_match_index(self._matches, cursor, direction)
        if index is None:
            return
        self._match_index = index
        start, end = self._matches[index]
        try:
            self.editor.tag_remove("find_current", "1.0", "end")
            self.editor.tag_add("find_current", f"1.0+{start}c", f"1.0+{end}c")
            self.editor.mark_set("insert", f"1.0+{end}c")
            self.editor.see(f"1.0+{start}c")
        except Exception:  # noqa: BLE001
            pass
        self.find_status.set(f"{index + 1} из {len(self._matches)}")

    def replace_current(self):
        if self._match_index is None or not self._matches:
            self.find_next(1)
        if self._match_index is None:
            return
        start, end = self._matches[self._match_index]
        try:
            self.editor.delete(f"1.0+{start}c", f"1.0+{end}c")
            self.editor.insert(f"1.0+{start}c", self.replace_var.get())
        except Exception:  # noqa: BLE001
            return
        self._on_modified_force()
        self._refresh_matches()
        self.find_next(1)

    def replace_all_in_file(self):
        try:
            text = self.editor.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            return
        new_text, count = replace_all(
            text, self.find_var.get(), self.replace_var.get(),
            case_sensitive=bool(self.match_case.get()))
        if not count:
            self.find_status.set("нет совпадений")
            return
        try:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", new_text)
        except Exception:  # noqa: BLE001
            return
        self._on_modified_force()
        self._refresh_matches()
        self.find_status.set(f"заменено: {count}")

    def _on_modified_force(self):
        if self._active is not None and 0 <= self._active < len(self._tabs):
            self._tabs[self._active]["modified"] = True
            self._render_tabs()
        self._schedule_highlight()

    # --------------------------------------------------- highlight + typing
    def _apply_highlight(self):
        self._highlight_after = None
        try:
            highlight(self.editor, self._language)
        except Exception:  # noqa: BLE001 - cosmetic only
            pass
        self._regen_gutter()
        self._redraw_minimap()

    def _schedule_highlight(self):
        if self._highlight_after is not None:
            try:
                self.after_cancel(self._highlight_after)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._highlight_after = self.after(400, self._apply_highlight)
        except Exception:  # noqa: BLE001 - fake widgets
            self._apply_highlight()

    def _on_key_release(self, event=None):
        self._update_cursor()
        self._schedule_highlight()
        self._highlight_bracket()
        if self.completion is None:
            return
        try:
            keysym = str(getattr(event, "keysym", "") or "")
        except Exception:  # noqa: BLE001
            keysym = ""
        if keysym in {"Up", "Down", "Return", "Tab", "Escape"}:
            return
        if keysym.isalnum() or keysym in {"underscore", "BackSpace", "period"}:
            self.completion.update()
        else:
            self.completion.hide()

    def _on_click(self, _event=None):
        self._update_cursor()
        self._highlight_bracket()
        if self.completion is not None:
            self.completion.hide()

    def _on_tab_key(self, _event=None):
        if self.completion is not None and self.completion.visible:
            self.completion.accept()
            return "break"
        try:
            self.editor.insert("insert", "    ")
        except Exception:  # noqa: BLE001
            pass
        return "break"

    def _on_escape(self, _event=None):
        if self.goto_visible:
            self.close_goto_line()
            return "break"
        if self.find_visible:
            self.close_find()
            return "break"
        if self.completion is not None and self.completion.visible:
            self.completion.hide()
            return "break"
        return None

    def _on_return_key(self, _event=None):
        if self.completion is not None and self.completion.visible:
            self.completion.accept()
            return "break"
        return None

    def _on_up_key(self, _event=None):
        if self.completion is not None and self.completion.visible:
            self.completion.move(-1)
            return "break"
        return None

    def _on_down_key(self, _event=None):
        if self.completion is not None and self.completion.visible:
            self.completion.move(1)
            return "break"
        return None

    # --------------------------------------------------------------- misc
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
        note = ""
        try:
            if self.format_on_save.get():
                content, fixes = format_source(content)
                if fixes:
                    self.editor.delete("1.0", "end")
                    self.editor.insert("1.0", content)
                    note = f" · формат: {fixes} исправлений"
        except Exception:  # noqa: BLE001 - formatting must not block saving
            pass
        try:
            tab["path"].write_text(content, encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Редактор", str(exc), parent=self)
            return
        tab["text"] = content
        tab["modified"] = False
        self._render_tabs()
        self.app.activity.log("file_edit", f"Сохранён файл {tab['path'].name}")
        if self.lint_on_save.get():
            try:
                self.run_lint()
                note += " · " + self.status_var.get()
            except Exception:  # noqa: BLE001 - linting must not block saving
                pass
        self.status_var.set(f"сохранено {time.strftime('%H:%M:%S')}{note}")
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
