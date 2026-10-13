"""Code editor page: tree + tabbed IDE editor with gutter, find/replace, bookmarks."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .finding import iter_matches, next_match_index, replace_all
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

        # Code area: gutter + editor + scrollbar
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
        scroll = ttk.Scrollbar(code_wrap, command=self.editor.yview)
        scroll.pack(side="right", fill="y")
        self.editor.configure(yscrollcommand=lambda a, b: self._sync_scroll(a, b))
        configure_tags(self.editor)
        self.editor.tag_configure("find_match", background="#8a6d1f")
        self.editor.tag_configure("find_current", background=C["accent"],
                                  foreground="#ffffff")
        self.editor.tag_configure("line_problem", background="#3f1d24")
        self.editor.bind("<Control-s>", lambda _e: (self.save_file(), "break")[1])
        self.editor.bind("<Control-w>", lambda _e: (self.close_tab(), "break")[1])
        self.editor.bind("<Control-Tab>", lambda _e: (self.next_tab(), "break")[1])
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
