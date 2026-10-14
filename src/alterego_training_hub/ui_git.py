"""Bottom-panel source control: changed files, diff preview, commit/push."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .git_manager import GitRepositoryError
from .i18n import t
from .ui_common import F_BASE, F_MONO, F_SMALL, C
from .vcs import classify_diff_lines, parse_numstat, parse_porcelain


class GitPanel(tk.Frame):
    """IDE source-control tab: status list + diff + commit actions."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=C["panel"])
        self.app = app
        self._rows: list[dict] = []
        self._build()

    def _build(self):
        top = tk.Frame(self, bg=C["panel"])
        top.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Button(top, text=t('Обновить'), command=self.refresh).pack(side="left")
        ttk.Button(top, text=t('Индексировать'),
                   command=self.stage_selected).pack(side="left", padx=6)
        ttk.Button(top, text=t('Снять из индекса'),
                   command=self.unstage_selected).pack(side="left")
        ttk.Button(top, text=t('Отменить изменения'),
                   command=self.discard_selected).pack(side="left", padx=6)
        self.branch_var = tk.StringVar(value="—")
        tk.Label(top, textvariable=self.branch_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left", padx=14)

        body = tk.Frame(self, bg=C["panel"])
        body.pack(fill="both", expand=True, padx=8, pady=6)

        left = tk.Frame(body, bg=C["panel"])
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, columns=("status", "file", "stat"),
                                 show="headings", height=7,
                                 selectmode="extended")
        self.tree.heading("status", text=t('Статус'))
        self.tree.heading("file", text=t('Файл'))
        self.tree.heading("stat", text="+/-")
        self.tree.column("status", width=110, anchor="w")
        self.tree.column("file", width=260, anchor="w")
        self.tree.column("stat", width=70, anchor="e")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_diff())
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        right = tk.Frame(body, bg=C["panel"])
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        commit_row = tk.Frame(right, bg=C["panel"])
        commit_row.pack(fill="x")
        tk.Label(commit_row, text=t('Сообщение'), bg=C["panel"],
                 font=F_BASE).pack(side="left")
        self.commit_var = tk.StringVar()
        tk.Entry(commit_row, textvariable=self.commit_var, bd=1,
                 relief="solid", font=F_BASE).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(commit_row, text=t('Закоммитить'), style="Accent.TButton",
                   command=self.commit_changes).pack(side="left")
        ttk.Button(commit_row, text="Push",
                   command=self.push_changes).pack(side="left", padx=4)
        ttk.Button(commit_row, text="Pull",
                   command=self.pull_changes).pack(side="left")

        self.diff = tk.Text(right, height=8, wrap="none", state="disabled",
                            bd=1, relief="solid", font=F_MONO,
                            bg=C["code_bg"], fg=C["code_fg"])
        self.diff.pack(fill="both", expand=True, pady=(6, 0))
        self.diff.tag_configure("vcs_add", foreground="#7ee787")
        self.diff.tag_configure("vcs_del", foreground="#ff7b72")
        self.diff.tag_configure("vcs_meta", foreground="#8b949e")
        self.diff.tag_configure("vcs_hunk", foreground="#79c0ff")

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(
            anchor="w", padx=10, pady=(0, 6))

    # ---------------------------------------------------------------- data
    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._rows = []
        root = self.app.workspace_root()
        if root is None:
            self.branch_var.set("—")
            self.status_var.set(t('Рабочая папка не выбрана.'))
            self._set_diff_text("")
            return
        try:
            status = self.app.git.status(root)
        except GitRepositoryError as exc:
            self.branch_var.set("—")
            self.status_var.set(f"Git: {str(exc)[:160]}")
            self._set_diff_text("")
            return
        self._rows = parse_porcelain("\n".join(status.changes))
        stats = {row["path"]: row for row in
                 parse_numstat(self.app.git.numstat(root))}
        for row in self._rows:
            stat = stats.get(row["path"])
            mark = (f"+{stat['added']}/-{stat['removed']}"
                    if stat is not None else "")
            self.tree.insert("", "end", iid=row["path"],
                             values=(row["label"], row["path"], mark))
        ahead = f" {status.ahead_behind}" if status.ahead_behind else ""
        self.branch_var.set(t('ветка: {v1}{ahead}').format(v1=status.branch, ahead=ahead))
        self.status_var.set(t('Изменений: {v1}').format(v1=len(self._rows)))
        self._show_selected_diff()
        badge = getattr(self.app, "_refresh_git_badge", None)
        if callable(badge):
            badge()

    def _selected_paths(self) -> list[str]:
        return list(self.tree.selection())

    def _row_for(self, path: str) -> dict | None:
        for row in self._rows:
            if row["path"] == path:
                return row
        return None

    def _show_selected_diff(self, path: str | None = None):
        root = self.app.workspace_root()
        if root is None:
            return
        if path is None:
            selected = self._selected_paths()
            path = selected[0] if selected else None
        try:
            if path is None:
                text = self.app.git.diff_text(root, against_head=True)
            else:
                row = self._row_for(path)
                if row is not None and row["staged"] and not row["unstaged"]:
                    text = self.app.git.diff_text(root, path=path, staged=True)
                else:
                    text = self.app.git.diff_text(root, path=path)
                if not text.strip():
                    text = t('(нет различий с HEAD — файл: {path})').format(path=path)
        except GitRepositoryError as exc:
            text = str(exc)[:2000]
        self._set_diff_text(text)

    def _set_diff_text(self, text: str):
        self.diff.configure(state="normal")
        self.diff.delete("1.0", "end")
        for kind, line in classify_diff_lines(text):
            tag = {"add": "vcs_add", "del": "vcs_del", "meta": "vcs_meta",
                   "hunk": "vcs_hunk"}.get(kind)
            if tag:
                self.diff.insert("end", line + "\n", tag)
            else:
                self.diff.insert("end", line + "\n")
        self.diff.configure(state="disabled")

    # ------------------------------------------------------------- actions
    def _act_on_selected(self, action, verb: str):
        root = self.app.workspace_root()
        paths = self._selected_paths()
        if root is None or not paths:
            self.status_var.set(t('Выберите файлы, чтобы {verb}.').format(verb=verb))
            return
        try:
            action(root, paths)
            self.status_var.set(t('Готово: {verb} ({v3} файл(ов)).').format(verb=verb, v3=len(paths)))
        except GitRepositoryError as exc:
            messagebox.showerror("Git", str(exc)[:500], parent=self)
        self.refresh()

    def stage_selected(self):
        self._act_on_selected(self.app.git.stage, t('проиндексировать'))

    def unstage_selected(self):
        self._act_on_selected(self.app.git.unstage, t('снять из индекса'))

    def discard_selected(self):
        paths = self._selected_paths()
        if not paths:
            self.status_var.set(t('Выберите файл, чтобы отменить изменения.'))
            return
        if not messagebox.askyesno(
            "Git",
            t('Отменить изменения в выбранных файлах? Несохранённые правки будут потеряны.'),
            parent=self,
        ):
            return
        root = self.app.workspace_root()
        if root is None:
            return
        try:
            for path in paths:
                self.app.git.discard_file(root, path)
            self.status_var.set(t('Изменения отменены: {v1} файл(ов).').format(v1=len(paths)))
        except GitRepositoryError as exc:
            messagebox.showerror("Git", str(exc)[:500], parent=self)
        self.refresh()

    def commit_changes(self):
        root = self.app.workspace_root()
        message = self.commit_var.get().strip()
        if root is None:
            self.status_var.set(t('Рабочая папка не выбрана.'))
            return
        if not message:
            self.status_var.set(t('Введите сообщение коммита.'))
            return
        try:
            output = self.app.git.commit(root, message)
        except GitRepositoryError as exc:
            messagebox.showerror("Git", str(exc)[:500], parent=self)
            return
        self.commit_var.set("")
        first = next((line for line in output.splitlines()
                      if line.strip() and not line.startswith("[")), "")
        self.status_var.set(t('Коммит создан. {v1}').format(v1=first[:120]))
        self.refresh()

    def push_changes(self):
        root = self.app.workspace_root()
        if root is None:
            self.status_var.set(t('Рабочая папка не выбрана.'))
            return
        try:
            self.app.git.push(root)
            self.status_var.set(t('Изменения отправлены (push).'))
        except GitRepositoryError as exc:
            messagebox.showerror("Git", str(exc)[:500], parent=self)

    def pull_changes(self):
        root = self.app.workspace_root()
        if root is None:
            self.status_var.set(t('Рабочая папка не выбрана.'))
            return
        try:
            self.app.git.pull_fast_forward(root)
            self.status_var.set(t('Обновления получены (pull --ff-only).'))
        except GitRepositoryError as exc:
            messagebox.showerror("Git", str(exc)[:500], parent=self)
        self.refresh()

    def open_selected(self):
        root = self.app.workspace_root()
        paths = self._selected_paths()
        if root is None or not paths:
            return
        target = Path(root) / paths[0]
        if target.is_file():
            self.app.pages["editor"].open_file(target)
