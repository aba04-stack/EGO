"""Tkinter desktop interface; network and Git operations run off the UI thread."""
from __future__ import annotations

import json
import math
import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .cloud_gpu import CloudGpuError, RunPodClient
from .config import AppSettings, SecretStore
from .git_manager import GitRepositoryError, GitRepositoryManager
from .mentor import ApiMentor


class TrainingHubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AlterEgo Training Hub")
        self.geometry("1080x760")
        self.minsize(880, 620)
        self.settings = AppSettings.load()
        self.secrets = SecretStore()
        self.git = GitRepositoryManager(timeout_seconds=600)
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="alterego-hub")
        self.events: queue.Queue = queue.Queue()
        self._gpu_rows: dict[str, dict] = {}
        self._pod_rows: dict[str, dict] = {}
        self._closing = False

        self._configure_style()
        self._build_header()
        self._build_tabs()
        self.status_text = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status_text, relief="sunken", anchor="w").pack(
            side="bottom", fill="x"
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)
        if self.settings.repo_path and Path(self.settings.repo_path).is_dir():
            self.after(350, self.refresh_repo_status)

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("SubHeader.TLabel", font=("Segoe UI", 10))
        style.configure("Action.TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=26)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_header(self):
        header = ttk.Frame(self, padding=(18, 14, 18, 10))
        header.pack(fill="x")
        ttk.Label(header, text="AlterEgo Training Hub", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Управление репозиториями, ИИ-наставниками и внешними GPU",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(3, 0))

    def _build_tabs(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.repo_tab = ttk.Frame(self.tabs, padding=14)
        self.mentor_tab = ttk.Frame(self.tabs, padding=14)
        self.gpu_tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(self.repo_tab, text="Репозитории")
        self.tabs.add(self.mentor_tab, text="ИИ-наставник")
        self.tabs.add(self.gpu_tab, text="Внешние GPU")
        self._build_repo_tab()
        self._build_mentor_tab()
        self._build_gpu_tab()

    def _section(self, parent, title: str, subtitle: str | None = None):
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        if subtitle:
            ttk.Label(frame, text=subtitle, wraplength=850).pack(anchor="w", pady=(0, 8))
        return frame

    def _build_repo_tab(self):
        tab = self.repo_tab
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(5, weight=1)

        ttk.Label(tab, text="Git URL").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.repo_url_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.repo_url_var).grid(
            row=0, column=1, sticky="ew", pady=4
        )
        ttk.Button(tab, text="Клонировать…", command=self.clone_repo).grid(
            row=0, column=2, padx=(8, 0), pady=4
        )

        ttk.Label(tab, text="Локальная папка").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.repo_path_var = tk.StringVar(value=self.settings.repo_path)
        ttk.Entry(tab, textvariable=self.repo_path_var).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        row_buttons = ttk.Frame(tab)
        row_buttons.grid(row=1, column=2, padx=(8, 0), pady=4)
        ttk.Button(row_buttons, text="Выбрать…", command=self.browse_repo).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(row_buttons, text="Подключить", command=self.connect_repo).pack(side="left")

        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 10))
        ttk.Button(actions, text="Обновить статус", style="Action.TButton",
                   command=self.refresh_repo_status).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Fetch", command=self.fetch_repo).pack(side="left", padx=6)
        ttk.Button(actions, text="Pull — только fast-forward", command=self.pull_repo).pack(
            side="left", padx=6
        )
        ttk.Label(actions, text="Ветка").pack(side="left", padx=(18, 5))
        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(
            actions, textvariable=self.branch_var, state="readonly", width=24
        )
        self.branch_combo.pack(side="left", padx=4)
        ttk.Button(actions, text="Переключить", command=self.checkout_branch).pack(
            side="left", padx=4
        )

        ttk.Label(
            tab,
            text=("Для приватных репозиториев используйте Git Credential Manager или GitHub CLI. "
                  "Пароль/токен не нужно добавлять в URL."),
            wraplength=900,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.repo_summary_var = tk.StringVar(value="Репозиторий не подключён")
        ttk.Label(tab, textvariable=self.repo_summary_var, font=("Segoe UI", 10, "bold")).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(2, 5)
        )
        self.repo_output = tk.Text(tab, height=12, wrap="word", state="disabled")
        self.repo_output.grid(row=5, column=0, columnspan=3, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.repo_output.yview)
        scroll.grid(row=5, column=3, sticky="ns")
        self.repo_output.configure(yscrollcommand=scroll.set)

    def _build_mentor_tab(self):
        tab = self.mentor_tab
        tab.columnconfigure(1, weight=1)
        ttk.Label(
            tab,
            text=("Подключается API-совместимый провайдер. Уточните его правила перед "
                  "использованием ответов для обучения моделей."),
            wraplength=900,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        fields = [
            ("Название провайдера", "mentor_provider", self.settings.mentor_provider),
            ("Базовый HTTPS URL", "mentor_base_url", self.settings.mentor_base_url),
            ("ID модели", "mentor_model", self.settings.mentor_model),
        ]
        self.mentor_vars = {}
        for idx, (label, key, value) in enumerate(fields, 1):
            ttk.Label(tab, text=label).grid(row=idx, column=0, sticky="w", padx=(0, 10), pady=5)
            var = tk.StringVar(value=value)
            self.mentor_vars[key] = var
            ttk.Entry(tab, textvariable=var).grid(row=idx, column=1, sticky="ew", pady=5)

        ttk.Label(tab, text="API-ключ").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=5)
        self.mentor_key_var = tk.StringVar()
        ttk.Entry(tab, textvariable=self.mentor_key_var, show="*").grid(
            row=4, column=1, sticky="ew", pady=5
        )
        self.mentor_secret_status = tk.StringVar(value=self._secret_status("mentor_api_key"))
        ttk.Label(tab, textvariable=self.mentor_secret_status).grid(
            row=4, column=2, sticky="w", padx=(10, 0)
        )

        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=(9, 10))
        ttk.Button(buttons, text="Сохранить настройки и ключ",
                   command=self.save_mentor).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Проверить соединение",
                   style="Action.TButton", command=self.test_mentor).pack(side="left", padx=6)
        ttk.Button(buttons, text="Удалить сохранённый ключ",
                   command=self.delete_mentor_key).pack(side="left", padx=6)

        prompt_frame = self._section(
            tab,
            "Проверочный запрос",
            "Нажатие кнопки теста отправит этот текст внешнему провайдеру и может расходовать API-кредиты.",
        )
        prompt_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(4, 10))
        self.mentor_prompt = tk.Text(prompt_frame, height=4, wrap="word")
        self.mentor_prompt.pack(fill="x")
        self.mentor_prompt.insert(
            "1.0",
            "Ты наставник проекта AlterEgo. Назови три объективно проверяемых способа "
            "улучшить качество маленькой языковой модели. Отдели факты от гипотез.",
        )

        output_frame = self._section(tab, "Ответ наставника")
        output_frame.grid(row=7, column=0, columnspan=3, sticky="nsew")
        tab.rowconfigure(7, weight=1)
        self.mentor_output = tk.Text(output_frame, height=9, wrap="word", state="disabled")
        self.mentor_output.pack(fill="both", expand=True)

    def _build_gpu_tab(self):
        tab = self.gpu_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        tab.rowconfigure(5, weight=1)

        auth = ttk.LabelFrame(tab, text="RunPod API", padding=8)
        auth.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        auth.columnconfigure(1, weight=1)
        ttk.Label(auth, text="API-ключ").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.runpod_key_var = tk.StringVar()
        ttk.Entry(auth, textvariable=self.runpod_key_var, show="*").grid(
            row=0, column=1, sticky="ew"
        )
        self.runpod_secret_status = tk.StringVar(value=self._secret_status("runpod_api_key"))
        ttk.Label(auth, textvariable=self.runpod_secret_status).grid(
            row=0, column=2, padx=8
        )
        ttk.Button(auth, text="Сохранить ключ", command=self.save_runpod_key).grid(
            row=0, column=3, padx=(0, 4)
        )

        gpu_frame = ttk.LabelFrame(tab, text="Каталог GPU — цены из API", padding=8)
        gpu_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        gpu_frame.columnconfigure(0, weight=1)
        bar = ttk.Frame(gpu_frame)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="Облако").pack(side="left", padx=(0, 6))
        self.cloud_var = tk.StringVar(value=self.settings.runpod_cloud)
        ttk.Combobox(bar, textvariable=self.cloud_var, values=("SECURE", "COMMUNITY"),
                     state="readonly", width=12).pack(side="left")
        ttk.Button(bar, text="Обновить каталог", style="Action.TButton",
                   command=self.refresh_gpu_catalog).pack(side="left", padx=8)
        ttk.Button(bar, text="Мои ресурсы", command=self.refresh_pods).pack(side="left", padx=4)

        gpu_columns = ("name", "id", "memory", "hourly", "availability")
        self.gpu_tree = ttk.Treeview(gpu_frame, columns=gpu_columns, show="headings", height=6)
        for col, title, width in [
            ("name", "Модель GPU", 250),
            ("id", "ID", 190),
            ("memory", "Память", 90),
            ("hourly", "Цена/час", 145),
            ("availability", "Доступность", 130),
        ]:
            self.gpu_tree.heading(col, text=title)
            self.gpu_tree.column(col, width=width, anchor="w")
        self.gpu_tree.grid(row=1, column=0, sticky="ew")
        gpu_scroll = ttk.Scrollbar(gpu_frame, orient="vertical", command=self.gpu_tree.yview)
        gpu_scroll.grid(row=1, column=1, sticky="ns")
        self.gpu_tree.configure(yscrollcommand=gpu_scroll.set)

        create_frame = ttk.LabelFrame(tab, text="Запуск GPU — оплата начнётся после создания", padding=8)
        create_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        create_frame.columnconfigure(1, weight=1)
        create_frame.columnconfigure(3, weight=1)
        self.gpu_budget_var = tk.StringVar(value=str(self.settings.runpod_max_gpu_hourly_usd))
        self.gpu_disk_var = tk.StringVar(value=str(self.settings.runpod_container_disk_gb))
        self.gpu_image_var = tk.StringVar(value=self.settings.runpod_image)
        self.gpu_name_var = tk.StringVar(value="alterego-training")
        ttk.Label(create_frame, text="Лимит цены GPU ($/час)").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(create_frame, textvariable=self.gpu_budget_var, width=12).grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(create_frame, text="Контейнерный диск (GB)").grid(row=0, column=2, sticky="w", padx=4, pady=3)
        ttk.Entry(create_frame, textvariable=self.gpu_disk_var, width=10).grid(row=0, column=3, sticky="ew", padx=4, pady=3)
        ttk.Label(create_frame, text="Имя ресурса").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(create_frame, textvariable=self.gpu_name_var).grid(row=1, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(create_frame, text="Образ контейнера").grid(row=1, column=2, sticky="w", padx=4, pady=3)
        ttk.Entry(create_frame, textvariable=self.gpu_image_var, width=38).grid(row=1, column=3, sticky="ew", padx=4, pady=3)
        ttk.Button(create_frame, text="Проверить цену и создать…",
                   command=self.create_gpu_pod).grid(row=2, column=0, columnspan=4, sticky="ew", padx=4, pady=(8, 2))
        ttk.Label(
            create_frame,
            text=("Лимит действует только на цену GPU, а не на весь счёт. "
                  "Контейнерный диск временный: сохраняйте чекпойнты отдельно."),
            wraplength=900,
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(5, 0))

        pod_frame = ttk.LabelFrame(tab, text="Мои GPU-ресурсы", padding=8)
        pod_frame.grid(row=3, column=0, sticky="ew")
        pod_frame.columnconfigure(0, weight=1)
        pods_columns = ("id", "name", "status", "gpu", "cost")
        self.pod_tree = ttk.Treeview(pod_frame, columns=pods_columns, show="headings", height=5)
        for col, title, width in [
            ("id", "ID", 180), ("name", "Имя", 230),
            ("status", "Статус", 120), ("gpu", "GPU", 180), ("cost", "Информация о расходах", 170),
        ]:
            self.pod_tree.heading(col, text=title)
            self.pod_tree.column(col, width=width, anchor="w")
        self.pod_tree.grid(row=0, column=0, sticky="ew")
        pod_scroll = ttk.Scrollbar(pod_frame, orient="vertical", command=self.pod_tree.yview)
        pod_scroll.grid(row=0, column=1, sticky="ns")
        self.pod_tree.configure(yscrollcommand=pod_scroll.set)
        pod_buttons = ttk.Frame(pod_frame)
        pod_buttons.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(pod_buttons, text="Остановить", command=lambda: self.pod_action("stop")).pack(side="left", padx=(0, 6))
        ttk.Button(pod_buttons, text="Возобновить", command=lambda: self.pod_action("start")).pack(side="left", padx=6)
        ttk.Button(pod_buttons, text="Удалить ресурс…", command=self.terminate_pod).pack(side="left", padx=6)

        self.gpu_notes_var = tk.StringVar(
            value="Подключите ключ RunPod и обновите каталог. Пока внешнее обучение моделей ещё не запускается автоматически."
        )
        ttk.Label(tab, textvariable=self.gpu_notes_var, wraplength=900).grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )

    def _secret_status(self, name: str) -> str:
        try:
            return "Ключ сохранён" if self.secrets.get(name) else "Ключ не сохранён"
        except Exception:
            return "Хранилище ключей недоступно"

    def _stored_or_typed(self, entry_var: tk.StringVar, secret_name: str) -> str:
        typed = entry_var.get().strip()
        if typed:
            return typed
        return self.secrets.get(secret_name)

    def _save_settings(self):
        self.settings.save()

    def _set_text(self, widget: tk.Text, value: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _start_async(self, label: str, task, success_callback=None):
        self.status_text.set(label)

        def work():
            try:
                result = task()
                self.events.put(("success", label, result, success_callback))
            except Exception as exc:
                self.events.put(("error", label, exc, None))

        try:
            self.executor.submit(work)
        except RuntimeError:
            self.status_text.set("Приложение закрывается")

    def _poll_events(self):
        if self._closing:
            return
        try:
            while True:
                kind, label, value, callback = self.events.get_nowait()
                if kind == "error":
                    self.status_text.set(f"Ошибка: {label}")
                    messagebox.showerror("AlterEgo Training Hub", str(value), parent=self)
                else:
                    self.status_text.set(f"Готово: {label}")
                    if callback:
                        try:
                            callback(value)
                        except Exception as exc:
                            self.status_text.set(f"Ошибка обработки результата: {label}")
                            messagebox.showerror(
                                "AlterEgo Training Hub",
                                f"Операция завершилась, но интерфейс не смог обновить результат: {exc}",
                                parent=self,
                            )
        except queue.Empty:
            pass
        self.after(120, self._poll_events)

    # Repository tab
    def browse_repo(self):
        path = filedialog.askdirectory(title="Выберите папку существующего Git-репозитория")
        if path:
            self.repo_path_var.set(path)

    def connect_repo(self):
        path = self.repo_path_var.get().strip()
        if not path:
            self.browse_repo()
            path = self.repo_path_var.get().strip()
        if not path:
            return
        self._start_async("Подключение репозитория", lambda: self.git.connect_local(path), self._repo_connected)

    def clone_repo(self):
        url = self.repo_url_var.get().strip()
        if not url:
            messagebox.showinfo("Репозиторий", "Введите HTTPS или SSH URL Git-репозитория.", parent=self)
            return
        parent = filedialog.askdirectory(title="Выберите папку, где создать копию репозитория")
        if not parent:
            return
        self._start_async("Клонирование Git-репозитория", lambda: self.git.clone(url, parent), self._repo_connected)

    def _repo_connected(self, path):
        self.settings.repo_path = str(path)
        if not self.settings.workspace_path:
            self.settings.workspace_path = str(Path(path).parent)
        self.repo_path_var.set(str(path))
        self._save_settings()
        self.refresh_repo_status()

    def _active_repo_path(self) -> Path:
        raw = self.repo_path_var.get().strip() or self.settings.repo_path
        if not raw:
            raise GitRepositoryError("Сначала подключите локальный Git-репозиторий или клонируйте его.")
        return Path(raw).expanduser()

    def refresh_repo_status(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            self.status_text.set(str(exc))
            return
        self._start_async("Получение состояния репозитория", lambda: self.git.status(path), self._show_repo_status)

    def _show_repo_status(self, result):
        self.repo_summary_var.set(f"{result.path}  ·  ветка: {result.branch}")
        lines = [
            f"Путь: {result.path}",
            f"Текущая ветка: {result.branch}",
            f"Origin: {result.remote or 'не настроен'}",
            f"Изменения: {len(result.changes)}",
            f"Ahead/behind (локальная/удалённая история): {result.ahead_behind or 'нет upstream'}",
            "",
            "Список незакоммиченных изменений:",
            *(result.changes or ("Нет незакоммиченных изменений.",)),
        ]
        self._set_text(self.repo_output, "\n".join(lines))
        try:
            branches = self.git.list_branches(result.path)
        except Exception:
            branches = []
        self.branch_combo["values"] = branches
        self.branch_var.set(result.branch if result.branch in branches else (branches[0] if branches else ""))

    def fetch_repo(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            messagebox.showerror("Репозиторий", str(exc), parent=self)
            return
        self._start_async("Получение изменений с сервера", lambda: self.git.refresh(path), lambda _: self.refresh_repo_status())

    def pull_repo(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            messagebox.showerror("Репозиторий", str(exc), parent=self)
            return
        if not messagebox.askyesno(
            "Обновить репозиторий",
            "Выполнить pull --ff-only? Локальные изменения не будут перезаписаны; "
            "при несовместимой истории операция завершится отказом.",
            parent=self,
        ):
            return
        self._start_async("Обновление репозитория (fast-forward only)", lambda: self.git.pull_fast_forward(path), lambda _: self.refresh_repo_status())

    def checkout_branch(self):
        try:
            path = self._active_repo_path()
        except GitRepositoryError as exc:
            messagebox.showerror("Репозиторий", str(exc), parent=self)
            return
        branch = self.branch_var.get().strip()
        if not branch:
            return
        if not messagebox.askyesno("Переключить ветку", f"Переключиться на ветку {branch}?", parent=self):
            return
        self._start_async("Переключение Git-ветки", lambda: self.git.checkout_branch(path, branch), lambda _: self.refresh_repo_status())

    # Mentor tab
    def save_mentor(self):
        self.settings.mentor_provider = self.mentor_vars["mentor_provider"].get().strip() or "OpenAI-compatible"
        self.settings.mentor_base_url = self.mentor_vars["mentor_base_url"].get().strip()
        self.settings.mentor_model = self.mentor_vars["mentor_model"].get().strip()
        key = self.mentor_key_var.get().strip()
        try:
            self._save_settings()
            if key:
                self.secrets.set("mentor_api_key", key)
                self.mentor_key_var.set("")
            self.mentor_secret_status.set(self._secret_status("mentor_api_key"))
            messagebox.showinfo(
                "ИИ-наставник",
                "Настройки сохранены. Ключ, если указан, сохранён в системном хранилище учётных данных.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)

    def delete_mentor_key(self):
        if not messagebox.askyesno("Удалить ключ", "Удалить сохранённый ключ наставника?", parent=self):
            return
        try:
            self.secrets.delete("mentor_api_key")
            self.mentor_secret_status.set(self._secret_status("mentor_api_key"))
            messagebox.showinfo("ИИ-наставник", "Ключ удалён из системного хранилища.", parent=self)
        except Exception as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)

    def test_mentor(self):
        base_url = self.mentor_vars["mentor_base_url"].get().strip()
        model = self.mentor_vars["mentor_model"].get().strip()
        prompt = self.mentor_prompt.get("1.0", "end").strip()
        key_var = self.mentor_key_var.get()
        try:
            key = key_var.strip() or self.secrets.get("mentor_api_key")
            mentor = ApiMentor(base_url, model, key)
        except Exception as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)
            return
        if not messagebox.askyesno(
            "Отправить проверочный запрос",
            "Текст из поля «Проверочный запрос» будет отправлен выбранному внешнему API. "
            "Запрос может расходовать кредиты провайдера. Продолжить?",
            parent=self,
        ):
            return

        def done(reply):
            self._set_text(
                self.mentor_output,
                reply.text + "\n\n---\n" + json.dumps({
                    "model": reply.model, "usage": reply.usage, "request_id": reply.request_id
                }, ensure_ascii=False, indent=2),
            )
            self.mentor_secret_status.set(self._secret_status("mentor_api_key"))

        self._start_async(
            "Проверка API-наставника",
            lambda: mentor.ask(prompt, max_tokens=500),
            done,
        )

    # Cloud GPU tab
    def _runpod_client(self) -> RunPodClient:
        key = self._stored_or_typed(self.runpod_key_var, "runpod_api_key")
        return RunPodClient(key)

    def save_runpod_key(self):
        key = self.runpod_key_var.get().strip()
        if not key:
            messagebox.showinfo("RunPod", "Введите API-ключ для сохранения.", parent=self)
            return
        try:
            self.secrets.set("runpod_api_key", key)
            self.runpod_key_var.set("")
            self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
            messagebox.showinfo("RunPod", "Ключ сохранён в системном хранилище.", parent=self)
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)

    def _persist_gpu_settings(self):
        try:
            budget = float(self.gpu_budget_var.get())
            disk = int(self.gpu_disk_var.get())
            if not math.isfinite(budget) or budget <= 0:
                raise ValueError("Цена в час должна быть положительной.")
            if not 10 <= disk <= 1000:
                raise ValueError("Контейнерный диск должен быть 10–1000 GB.")
            self.settings.runpod_cloud = self.cloud_var.get().upper()
            self.settings.runpod_max_gpu_hourly_usd = budget
            self.settings.runpod_container_disk_gb = disk
            self.settings.runpod_image = self.gpu_image_var.get().strip()
            self.settings.save()
            return budget, disk
        except ValueError as exc:
            raise CloudGpuError(str(exc)) from None

    def refresh_gpu_catalog(self):
        try:
            client = self._runpod_client()
            self._persist_gpu_settings()
            cloud = self.cloud_var.get().upper()
        except Exception as exc:
            messagebox.showerror("Внешние GPU", str(exc), parent=self)
            return
        self._start_async("Загрузка актуального каталога GPU", lambda: client.gpu_catalog(cloud), self._show_gpu_catalog)

    @staticmethod
    def _price_text(gpu):
        prices = gpu.get("price")
        values = []
        for cloud_name, top_level in (
            ("secure", "securePrice"),
            ("community", "communityPrice"),
        ):
            value = prices.get(cloud_name) if isinstance(prices, dict) else None
            if value is None:
                value = gpu.get(top_level)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(f"{cloud_name}: ${float(value):.3f}/ч")
        return " · ".join(values) or "цена не получена"

    def _show_gpu_catalog(self, items):
        self._gpu_rows.clear()
        for iid in self.gpu_tree.get_children():
            self.gpu_tree.delete(iid)
        for index, gpu in enumerate(items):
            iid = f"gpu-{index}"
            self._gpu_rows[iid] = gpu
            memory = gpu.get("memory", gpu.get("memoryInGb", "—"))
            availability = gpu.get("availability", gpu.get("maxGpuCount", "—"))
            if isinstance(availability, dict):
                availability = availability.get("available", availability.get("status", "—"))
            if isinstance(availability, (dict, list)):
                availability = json.dumps(availability, ensure_ascii=False)
            self.gpu_tree.insert("", "end", iid=iid, values=(
                gpu.get("name", gpu.get("displayName", "Unknown GPU")),
                gpu.get("id", ""),
                memory,
                self._price_text(gpu),
                str(availability),
            ))
        self.gpu_notes_var.set(f"Получено GPU из текущего каталога: {len(items)}. Выбери GPU для расчёта цены.")

    def refresh_pods(self):
        try:
            client = self._runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self._start_async("Загрузка ресурсов RunPod", lambda: client.list_pods(), self._show_pods)

    def _show_pods(self, items):
        self._pod_rows.clear()
        for iid in self.pod_tree.get_children():
            self.pod_tree.delete(iid)
        for index, pod in enumerate(items):
            iid = f"pod-{index}"
            self._pod_rows[iid] = pod
            gpu = pod.get("gpu", pod.get("gpuTypeId", "—"))
            if isinstance(gpu, dict):
                gpu = gpu.get("id", gpu.get("name", "—"))
            cost = pod.get("cost", pod.get("costPerHr", "—"))
            self.pod_tree.insert("", "end", iid=iid, values=(
                pod.get("id", ""), pod.get("name", ""), pod.get("status", ""),
                gpu, str(cost),
            ))
        self.gpu_notes_var.set(f"Ресурсов в аккаунте: {len(items)}. Проверяй их состояние и расходы регулярно.")

    def create_gpu_pod(self):
        selected = self.gpu_tree.selection()
        if not selected:
            messagebox.showinfo("Внешние GPU", "Сначала выбери GPU в каталоге.", parent=self)
            return
        gpu = self._gpu_rows.get(selected[0])
        if not gpu or not gpu.get("id"):
            messagebox.showerror("Внешние GPU", "У выбранной записи нет GPU ID.", parent=self)
            return
        try:
            client = self._runpod_client()
            budget, disk = self._persist_gpu_settings()
            plan = client.plan_pod(
                gpu_id=str(gpu["id"]),
                max_gpu_hourly_usd=budget,
                cloud=self.cloud_var.get().upper(),
                image=self.gpu_image_var.get().strip(),
                container_disk_gb=disk,
                name=self.gpu_name_var.get().strip(),
            )
        except Exception as exc:
            messagebox.showerror("Проверка цены", str(exc), parent=self)
            return

        confirmation = (
            f"GPU: {plan['gpu_name']}\n"
            f"Тариф GPU: ${plan['gpu_hourly_usd']:.4f} в час\n"
            f"Лимит тарифа GPU: ${plan['gpu_only_budget_usd']:.4f} в час\n"
            f"Контейнерный диск: {plan['container_disk_gb']} GB\n\n"
            "Это не общий лимит расходов: могут отдельно тарифицироваться хранилище и другие услуги. "
            "Данные на временном контейнерном диске могут исчезнуть после удаления ресурса.\n\n"
            "Создать платный ресурс сейчас?"
        )
        if not messagebox.askyesno("Подтверждение расходов", confirmation, parent=self):
            return
        self._start_async(
            "Создание платного GPU-ресурса",
            lambda: client.create_pod(plan, confirmed=True),
            lambda created: self._after_gpu_created(created),
        )

    def _after_gpu_created(self, pod):
        self.gpu_notes_var.set(
            f"Создан ресурс {pod.get('id', '')}. Проверь его статус, расходы и доступ к среде."
        )
        self.refresh_pods()
        messagebox.showinfo(
            "GPU создана",
            f"ID: {pod.get('id', 'не указан')}\n"
            "Создание облачного ресурса не означает, что обучение уже запущено. "
            "Настройка удалённого исполнителя обучения будет следующим этапом.",
            parent=self,
        )

    def _selected_pod(self):
        selected = self.pod_tree.selection()
        if not selected:
            messagebox.showinfo("GPU", "Сначала выбери ресурс из списка.", parent=self)
            return None
        pod = self._pod_rows.get(selected[0])
        if not pod or not pod.get("id"):
            messagebox.showerror("GPU", "У выбранного ресурса нет ID.", parent=self)
            return None
        return pod

    def pod_action(self, action: str):
        pod = self._selected_pod()
        if not pod:
            return
        action_title = "остановить" if action == "stop" else "возобновить"
        if not messagebox.askyesno(
            "Управление GPU",
            f"Подтверждаешь действие «{action_title}» для ресурса {pod['id']}?",
            parent=self,
        ):
            return
        try:
            client = self._runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self._start_async(
            f"Действие RunPod: {action}",
            lambda: client.pod_action(str(pod["id"]), action, confirmed=True),
            lambda _: self.refresh_pods(),
        )

    def terminate_pod(self):
        pod = self._selected_pod()
        if not pod:
            return
        if not messagebox.askyesno(
            "Безвозвратное удаление",
            f"Удалить GPU-ресурс {pod['id']}? Это разрушительное действие. "
            "Данные на контейнерном диске могут быть потеряны. "
            "Проверь отдельно, какие расходы могут продолжиться у сохранённых ресурсов.",
            parent=self,
        ):
            return
        try:
            client = self._runpod_client()
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)
            return
        self._start_async(
            "Удаление GPU-ресурса",
            lambda: client.terminate_pod(str(pod["id"]), confirmed=True),
            lambda _: self.refresh_pods(),
        )

    def _on_close(self):
        self._closing = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main():
    app = TrainingHubApp()
    app.mainloop()
