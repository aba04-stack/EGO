"""Workspace page: choose the working folder and manage the Git repository."""
from __future__ import annotations
from .i18n import t

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .git_manager import GitRepositoryError
from .ui_common import C, F_BASE, F_SMALL, card, page_header, set_text


class WorkspacePage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._build()

    def _build(self):
        header = page_header(
            self,
            t('Рабочая папка'),
            t('Выберите папку на компьютере, с которой работает ИИ-наставник и обучение. Все инструменты наставника ограничены этой папкой.'),
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        # Working folder card
        folder_card = card(self, t('Папка для работы ИИ и обучения'))
        folder_card.pack(fill="x", padx=24, pady=(0, 12))
        row = tk.Frame(folder_card, bg=C["panel"])
        row.pack(fill="x", pady=(8, 0))
        self.workspace_var = tk.StringVar(value=self.app.settings.workspace_path)
        tk.Entry(row, textvariable=self.workspace_var, bd=1, relief="solid",
                 font=F_BASE).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(row, text=t('Обзор…'), command=self.browse_workspace).pack(side="left")
        ttk.Button(row, text=t('Использовать эту папку'), style="Accent.TButton",
                   command=self.save_workspace).pack(side="left", padx=(8, 0))
        tk.Label(
            folder_card,
            text=t('Подсказка: можно указать синхронизируемую облаком папку (OneDrive, Яндекс.Диск и т.п.), чтобы проект был доступен с других устройств.'),
            bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860, justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # Git card
        git_card = card(self, t('Git-репозиторий'))
        git_card.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        git_card.columnconfigure(1, weight=1)

        tk.Label(git_card, text="Git URL", bg=C["panel"], font=F_BASE).grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        self.repo_url_var = tk.StringVar()
        tk.Entry(git_card, textvariable=self.repo_url_var, bd=1, relief="solid",
                 font=F_BASE).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(git_card, text=t('Клонировать…'), command=self.clone_repo).grid(
            row=0, column=2, padx=(8, 0), pady=6)

        tk.Label(git_card, text=t('Локальная папка'), bg=C["panel"], font=F_BASE).grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        self.repo_path_var = tk.StringVar(value=self.app.settings.repo_path)
        tk.Entry(git_card, textvariable=self.repo_path_var, bd=1, relief="solid",
                 font=F_BASE).grid(row=1, column=1, sticky="ew", pady=6)
        repo_btns = tk.Frame(git_card, bg=C["panel"])
        repo_btns.grid(row=1, column=2, padx=(8, 0), pady=6)
        ttk.Button(repo_btns, text=t('Выбрать…'), command=self.browse_repo).pack(
            side="left", padx=(0, 4))
        ttk.Button(repo_btns, text=t('Подключить'), command=self.connect_repo).pack(side="left")

        actions = tk.Frame(git_card, bg=C["panel"])
        actions.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 4))
        ttk.Button(actions, text=t('Обновить статус'), style="Accent.TButton",
                   command=self.refresh_repo_status).pack(side="left")
        ttk.Button(actions, text="Fetch", command=self.fetch_repo).pack(side="left", padx=8)
        ttk.Button(actions, text=t('Pull — только fast-forward'),
                   command=self.pull_repo).pack(side="left", padx=8)
        tk.Label(actions, text=t('Ветка'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(16, 6))
        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(actions, textvariable=self.branch_var,
                                         state="readonly", width=24)
        self.branch_combo.pack(side="left")
        ttk.Button(actions, text=t('Переключить'), command=self.checkout_branch).pack(
            side="left", padx=8)

        tk.Label(
            git_card,
            text=t('Для приватных репозиториев используйте Git Credential Manager или GitHub CLI. Пароль/токен не нужно добавлять в URL.'),
            bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860, justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 4))

        self.repo_summary_var = tk.StringVar(value=t('Репозиторий не подключён'))
        tk.Label(git_card, textvariable=self.repo_summary_var, bg=C["panel"],
                 font=("Segoe UI", 10, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 4))

        self.repo_output = tk.Text(git_card, height=11, wrap="word", state="disabled",
                                   bd=1, relief="solid", font=("Consolas", 9))
        self.repo_output.grid(row=5, column=0, columnspan=3, sticky="nsew")
        git_card.rowconfigure(5, weight=1)
        scroll = ttk.Scrollbar(git_card, orient="vertical", command=self.repo_output.yview)
        scroll.grid(row=5, column=3, sticky="ns")
        self.repo_output.configure(yscrollcommand=scroll.set)

    # ------------------------------------------------------------ workspace
    def browse_workspace(self):
        path = filedialog.askdirectory(title=t('Выберите рабочую папку'))
        if path:
            self.workspace_var.set(path)

    def save_workspace(self):
        raw = self.workspace_var.get().strip()
        if raw:
            path = Path(raw).expanduser()
            if not path.is_dir():
                messagebox.showerror(t('Рабочая папка'), t('Папка не существует.'), parent=self)
                return
        self.app.settings.workspace_path = raw
        self.app.save_settings()
        self.app.set_status(t('Рабочая папка сохранена'))
        chat = self.app.pages.get("chat")
        if chat is not None:
            chat.on_show()

    # ----------------------------------------------------------------- git
    def browse_repo(self):
        path = filedialog.askdirectory(title=t('Выберите папку Git-репозитория'))
        if path:
            self.repo_path_var.set(path)

    def connect_repo(self):
        path = self.repo_path_var.get().strip()
        if not path:
            self.browse_repo()
            path = self.repo_path_var.get().strip()
        if not path:
            return
        self.app.start_async(t('Подключение репозитория'),
                             lambda: self.app.git.connect_local(path),
                             self._repo_connected)

    def clone_repo(self):
        url = self.repo_url_var.get().strip()
        if not url:
            messagebox.showinfo(t('Репозиторий'), t('Введите HTTPS или SSH URL.'), parent=self)
            return
        parent = filedialog.askdirectory(title=t('Куда клонировать репозиторий?'))
        if not parent:
            return
        self.app.start_async(t('Клонирование Git-репозитория'),
                             lambda: self.app.git.clone(url, parent),
                             self._repo_connected)

    def _repo_connected(self, path):
        self.app.settings.repo_path = str(path)
        if not self.app.settings.workspace_path:
            self.app.settings.workspace_path = str(Path(path).parent)
            self.workspace_var.set(self.app.settings.workspace_path)
        self.repo_path_var.set(str(path))
        self.app.save_settings()
        self.refresh_repo_status()

    def _active_repo_path(self) -> Path:
        raw = self.repo_path_var.get().strip() or self.app.settings.repo_path
        if not raw:
            raise GitRepositoryError(t('Сначала подключите локальный Git-репозиторий.'))
        return Path(raw).expanduser()

    def refresh_repo_status(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            self.app.set_status(str(exc))
            return
        self.app.start_async(t('Получение состояния репозитория'),
                             lambda: self.app.git.status(path),
                             self._show_repo_status)

    def _show_repo_status(self, result):
        self.repo_summary_var.set(t('{v0}  ·  ветка: {v2}').format(v0=result.path, v2=result.branch))
        lines = [
            t('Путь: {v1}').format(v1=result.path),
            t('Текущая ветка: {v1}').format(v1=result.branch),
            f"Origin: {result.remote or t('не настроен')}",
            t('Изменения: {v1}').format(v1=len(result.changes)),
            f"Ahead/behind: {result.ahead_behind or t('нет upstream')}",
            "",
            t('Незакоммиченные изменения:'),
            *(result.changes or (t('нет'),)),
        ]
        set_text(self.repo_output, "\n".join(lines))
        try:
            branches = self.app.git.list_branches(result.path)
        except Exception:
            branches = []
        self.branch_combo["values"] = branches
        self.branch_var.set(result.branch if result.branch in branches
                            else (branches[0] if branches else ""))

    def fetch_repo(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            messagebox.showerror(t('Репозиторий'), str(exc), parent=self)
            return
        self.app.start_async(t('Получение изменений с сервера'),
                             lambda: self.app.git.refresh(path),
                             lambda _: self.refresh_repo_status())

    def pull_repo(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            messagebox.showerror(t('Репозиторий'), str(exc), parent=self)
            return
        if not messagebox.askyesno(
            t('Обновить репозиторий'),
            t('Выполнить pull --ff-only? Локальные изменения не будут перезаписаны.'),
            parent=self,
        ):
            return
        self.app.start_async(t('Обновление репозитория'),
                             lambda: self.app.git.pull_fast_forward(path),
                             lambda _: self.refresh_repo_status())

    def checkout_branch(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            messagebox.showerror(t('Репозиторий'), str(exc), parent=self)
            return
        branch = self.branch_var.get().strip()
        if not branch:
            return
        if not messagebox.askyesno(t('Переключить ветку'),
                                   t('Переключиться на ветку {branch}?').format(branch=branch), parent=self):
            return
        self.app.start_async(t('Переключение Git-ветки'),
                             lambda: self.app.git.checkout_branch(path, branch),
                             lambda _: self.refresh_repo_status())
