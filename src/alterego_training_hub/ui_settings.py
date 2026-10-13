"""Settings page: mentor provider, model list, API keys, folders."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .diagnostics import diagnostics_summary, diagnostics_text, run_diagnostics
from .logging_setup import log_file, tail_log
from .mentor import MentorError
from .ui_common import C, F_BASE, F_MONO, F_SMALL, Collapsible, page_header, set_text


class SettingsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._last_diag = ""
        self._build()

    def _build(self):
        header = page_header(
            self,
            "Настройки",
            "Подключение ИИ-наставника, ключи API и папки. Ключи хранятся только "
            "в системном хранилище учётных данных и не попадают в файлы проекта.",
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        # Mentor provider
        mentor_section = Collapsible(self, "ИИ-наставник (OpenAI-совместимый API)")
        mentor_section.pack(fill="x", padx=24, pady=(0, 12))
        mentor_section.set_hint("свернуть/развернуть")
        mentor_card = mentor_section.body
        mentor_card.columnconfigure(1, weight=1)

        self.mentor_vars: dict[str, tk.StringVar] = {}
        fields = [
            ("Название провайдера", "mentor_provider", self.app.settings.mentor_provider),
            ("Базовый HTTPS URL", "mentor_base_url", self.app.settings.mentor_base_url),
        ]
        for row, (label, key, value) in enumerate(fields):
            tk.Label(mentor_card, text=label, bg=C["panel"], font=F_BASE).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            var = tk.StringVar(value=value)
            self.mentor_vars[key] = var
            tk.Entry(mentor_card, textvariable=var, bd=1, relief="solid",
                     font=F_BASE).grid(row=row, column=1, sticky="ew", pady=5)

        tk.Label(mentor_card, text="ID модели", bg=C["panel"], font=F_BASE).grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=5)
        self.model_var = tk.StringVar(value=self.app.settings.mentor_model)
        self.model_combo = ttk.Combobox(mentor_card, textvariable=self.model_var,
                                        font=F_BASE)
        self.model_combo.grid(row=2, column=1, sticky="ew", pady=5)

        gen_row = tk.Frame(mentor_card, bg=C["panel"])
        gen_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=5)
        tk.Label(gen_row, text="Температура", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.temp_var = tk.StringVar(value=str(self.app.settings.mentor_temperature))
        tk.Entry(gen_row, textvariable=self.temp_var, width=6, bd=1, relief="solid",
                 font=F_BASE).pack(side="left", padx=(0, 16))
        tk.Label(gen_row, text="Макс. токенов ответа", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.tokens_var = tk.StringVar(value=str(self.app.settings.mentor_max_tokens))
        tk.Entry(gen_row, textvariable=self.tokens_var, width=8, bd=1, relief="solid",
                 font=F_BASE).pack(side="left")

        key_row = tk.Frame(mentor_card, bg=C["panel"])
        key_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=5)
        tk.Label(key_row, text="API-ключ", bg=C["panel"], font=F_BASE).pack(side="left",
                                                                           padx=(0, 8))
        self.mentor_key_var = tk.StringVar()
        tk.Entry(key_row, textvariable=self.mentor_key_var, show="•", bd=1,
                 relief="solid", font=F_BASE, width=40).pack(side="left")
        self.mentor_secret_status = tk.StringVar(
            value=self._secret_status("mentor_api_key"))
        tk.Label(key_row, textvariable=self.mentor_secret_status, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left", padx=10)

        btn_row = tk.Frame(mentor_card, bg=C["panel"])
        btn_row.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(btn_row, text="Сохранить настройки и ключ",
                   style="Accent.TButton", command=self.save_mentor).pack(side="left")
        ttk.Button(btn_row, text="Получить список моделей",
                   command=self.fetch_models).pack(side="left", padx=8)
        ttk.Button(btn_row, text="Проверить соединение",
                   command=self.test_mentor).pack(side="left", padx=8)
        ttk.Button(btn_row, text="Удалить сохранённый ключ",
                   style="Danger.TButton", command=self.delete_mentor_key).pack(side="left",
                                                                                padx=8)

        # Keys for cloud
        keys_section = Collapsible(self, "Ключи облачных сервисов")
        keys_section.pack(fill="x", padx=24, pady=(0, 12))
        keys_card = keys_section.body
        row = tk.Frame(keys_card, bg=C["panel"])
        row.pack(fill="x")
        tk.Label(row, text="RunPod API-ключ", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.runpod_key_var = tk.StringVar()
        tk.Entry(row, textvariable=self.runpod_key_var, show="•", bd=1, relief="solid",
                 font=F_BASE, width=40).pack(side="left")
        self.runpod_secret_status = tk.StringVar(
            value=self._secret_status("runpod_api_key"))
        tk.Label(row, textvariable=self.runpod_secret_status, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left", padx=10)
        ttk.Button(row, text="Сохранить ключ", command=self.save_runpod_key).pack(
            side="left")
        ttk.Button(row, text="Удалить ключ", style="Danger.TButton",
                   command=self.delete_runpod_key).pack(side="left", padx=8)

        # Folders
        folders_section = Collapsible(self, "Папки")
        folders_section.pack(fill="x", padx=24, pady=(0, 12))
        folders_card = folders_section.body
        folders_card.columnconfigure(1, weight=1)

        self.workspace_var = tk.StringVar(value=self.app.settings.workspace_path)
        self.library_var = tk.StringVar(value=self.app.settings.model_library_path)
        for row, (label, var, command) in enumerate([
            ("Рабочая папка (ИИ + обучение)", self.workspace_var, self.pick_workspace),
            ("Библиотека моделей (можно облако)", self.library_var, self.pick_library),
        ]):
            tk.Label(folders_card, text=label, bg=C["panel"], font=F_BASE).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            tk.Entry(folders_card, textvariable=var, bd=1, relief="solid",
                     font=F_BASE).grid(row=row, column=1, sticky="ew", pady=5)
            ttk.Button(folders_card, text="Обзор…", command=command).grid(
                row=row, column=2, padx=(8, 0), pady=5)
        ttk.Button(folders_card, text="Сохранить папки",
                   command=self.save_folders).grid(row=2, column=1, sticky="w", pady=8)

        # Diagnostics
        diag_section = Collapsible(self, "Диагностика и логи")
        diag_section.pack(fill="x", padx=24, pady=(0, 12))
        diag_section.set_hint("свернуть/развернуть")
        diag = diag_section.body
        self.diag_status = tk.StringVar(value="Проверка окружения: Python, хранилище "
                                              "ключей, SSH, Git, папки, диск.")
        tk.Label(diag, textvariable=self.diag_status, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL, wraplength=860, justify="left").pack(anchor="w")
        btns = tk.Frame(diag, bg=C["panel"])
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Запустить проверку", style="Accent.TButton",
                   command=self.run_check).pack(side="left")
        ttk.Button(btns, text="Скопировать отчёт",
                   command=self.copy_diag).pack(side="left", padx=8)
        ttk.Button(btns, text="Показать лог ошибок",
                   command=self.show_log).pack(side="left", padx=8)
        self.diag_text = tk.Text(diag, height=8, wrap="word", state="disabled",
                                 bd=1, relief="solid", font=F_MONO)
        self.diag_text.pack(fill="x", pady=(8, 2))

        tk.Label(
            self,
            text="Ключи хранятся через системный диспетчер учётных данных (keyring). "
                 "Настройки — в профиле пользователя, без секретов.",
            bg=C["bg"], fg=C["muted"], font=F_SMALL,
        ).pack(anchor="w", padx=24, pady=(0, 14))

    # -------------------------------------------------------------- helpers
    def _secret_status(self, name: str) -> str:
        try:
            return "Ключ сохранён" if self.app.secrets.get(name) else "Ключ не сохранён"
        except Exception:
            return "Хранилище ключей недоступно"

    def run_check(self):
        self.diag_status.set("Выполняется проверка…")

        def done(results):
            summary = diagnostics_summary(results)
            self._last_diag = diagnostics_text(results)
            set_text(self.diag_text, self._last_diag)
            self.diag_status.set(
                f"Проверка завершена: ошибок — {summary['errors']}, "
                f"предупреждений — {summary['warnings']}.")

        self.app.start_async("Диагностика",
                             lambda: run_diagnostics(self.app.settings,
                                                     self.app.secrets),
                             done)

    def copy_diag(self):
        text = self._last_diag or self.diag_text.get("1.0", "end")
        if not text.strip():
            messagebox.showinfo("Диагностика", "Сначала запустите проверку.",
                                parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def show_log(self):
        tail = tail_log(12000)
        set_text(self.diag_text, tail or "Лог пуст.")
        self.diag_status.set(f"Файл лога: {log_file()}")

    def on_show(self):
        self.mentor_secret_status.set(self._secret_status("mentor_api_key"))
        self.runpod_secret_status.set(self._secret_status("runpod_api_key"))

    # ------------------------------------------------------------- handlers
    def _collect_mentor(self):
        self.app.settings.mentor_provider = (
            self.mentor_vars["mentor_provider"].get().strip() or "OpenAI-compatible")
        self.app.settings.mentor_base_url = self.mentor_vars["mentor_base_url"].get().strip()
        self.app.settings.mentor_model = self.model_var.get().strip()
        try:
            temperature = float(self.temp_var.get())
            max_tokens = int(self.tokens_var.get())
        except ValueError:
            raise MentorError("Температура и максимум токенов должны быть числами.") from None
        if not 0 <= temperature <= 2:
            raise MentorError("Температура должна быть от 0 до 2.")
        if not 1 <= max_tokens <= 8000:
            raise MentorError("Максимум токенов: от 1 до 8000.")
        self.app.settings.mentor_temperature = temperature
        self.app.settings.mentor_max_tokens = max_tokens

    def save_mentor(self):
        try:
            self._collect_mentor()
            self.app.save_settings()
            key = self.mentor_key_var.get().strip()
            if key:
                self.app.secrets.set("mentor_api_key", key)
                self.mentor_key_var.set("")
            self.mentor_secret_status.set(self._secret_status("mentor_api_key"))
            messagebox.showinfo(
                "ИИ-наставник",
                "Настройки сохранены. Ключ (если указан) сохранён в системном "
                "хранилище учётных данных.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)

    def fetch_models(self):
        try:
            self._collect_mentor()
            self.app.save_settings()
            client = self.app.mentor_client()
        except Exception as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)
            return

        def done(models):
            self.model_combo.configure(values=models)
            if self.model_var.get() not in models and models:
                self.model_var.set(models[0])
            messagebox.showinfo("Модели", f"Получено моделей: {len(models)}", parent=self)

        self.app.start_async("Получение списка моделей", client.list_models, done)

    def test_mentor(self):
        try:
            self._collect_mentor()
            self.app.save_settings()
            client = self.app.mentor_client()
        except Exception as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)
            return
        if not messagebox.askyesno(
            "Отправить проверочный запрос",
            "Тестовый запрос будет отправлен внешнему API и может расходовать "
            "кредиты провайдера. Продолжить?",
            parent=self,
        ):
            return

        def done(reply):
            messagebox.showinfo(
                "Соединение работает",
                f"Модель: {reply.model}\n\n{reply.text[:500]}",
                parent=self,
            )

        self.app.start_async(
            "Проверка соединения с наставником",
            lambda: client.ask("Ответь одним словом: готов.", max_tokens=20),
            done,
        )

    def delete_mentor_key(self):
        if not messagebox.askyesno("Удалить ключ", "Удалить сохранённый ключ наставника?",
                                   parent=self):
            return
        try:
            self.app.secrets.delete("mentor_api_key")
            self.mentor_secret_status.set(self._secret_status("mentor_api_key"))
            messagebox.showinfo("ИИ-наставник", "Ключ удалён.", parent=self)
        except Exception as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)

    def save_runpod_key(self):
        key = self.runpod_key_var.get().strip()
        if not key:
            messagebox.showinfo("RunPod", "Введите API-ключ для сохранения.", parent=self)
            return
        try:
            self.app.secrets.set("runpod_api_key", key)
            self.runpod_key_var.set("")
            self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
            messagebox.showinfo("RunPod", "Ключ сохранён в системном хранилище.",
                                parent=self)
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)

    def delete_runpod_key(self):
        if not messagebox.askyesno("Удалить ключ", "Удалить ключ RunPod?", parent=self):
            return
        try:
            self.app.secrets.delete("runpod_api_key")
            self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)

    def pick_workspace(self):
        path = filedialog.askdirectory(title="Рабочая папка")
        if path:
            self.workspace_var.set(path)

    def pick_library(self):
        path = filedialog.askdirectory(title="Библиотека моделей")
        if path:
            self.library_var.set(path)

    def save_folders(self):
        for var in (self.workspace_var, self.library_var):
            raw = var.get().strip()
            if raw and not Path(raw).expanduser().is_dir():
                messagebox.showerror("Папки", f"Папка не существует: {raw}", parent=self)
                return
        self.app.settings.workspace_path = self.workspace_var.get().strip()
        self.app.settings.model_library_path = self.library_var.get().strip()
        self.app.save_settings()
        messagebox.showinfo("Папки", "Папки сохранены.", parent=self)
        chat = self.app.pages.get("chat")
        if chat is not None:
            chat.on_show()
