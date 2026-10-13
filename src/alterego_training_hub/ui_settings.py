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
        # Provider picker: id -> label from the shared registry.
        from .llm_providers import provider_info, provider_labels

        tk.Label(mentor_card, text="Провайдер ИИ", bg=C["panel"],
                 font=F_BASE).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        current_label = provider_info(self.app.settings.llm_provider).label
        self.provider_var = tk.StringVar(value=current_label)
        self.provider_combo = ttk.Combobox(
            mentor_card, textvariable=self.provider_var,
            values=provider_labels(), state="readonly", font=F_BASE)
        self.provider_combo.grid(row=0, column=1, sticky="ew", pady=5)
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_selected)

        tk.Label(mentor_card, text="Базовый URL", bg=C["panel"],
                 font=F_BASE).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        base_value = self.app.settings.mentor_base_url \
            or provider_info(self.app.settings.llm_provider).base_url
        self.mentor_vars["mentor_base_url"] = tk.StringVar(value=base_value)
        tk.Entry(mentor_card, textvariable=self.mentor_vars["mentor_base_url"],
                 bd=1, relief="solid", font=F_BASE).grid(
            row=1, column=1, sticky="ew", pady=5)

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

        # Agent behaviour
        agent_section = Collapsible(self, "ИИ-агент: точность и возможности")
        agent_section.pack(fill="x", padx=24, pady=(0, 12))
        agent_section.set_hint("свернуть/развернуть")
        agent_card = agent_section.body
        agent_card.columnconfigure(1, weight=1)

        profile_row = tk.Frame(agent_card, bg=C["panel"])
        profile_row.pack(fill="x")
        tk.Label(profile_row, text="Профиль агента", bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        from .agent_profiles import profile_info, profile_labels

        current_profile = profile_info(self.app.settings.agent_profile)
        self.agent_profile_var = tk.StringVar(value=current_profile.label)
        ttk.Combobox(profile_row, textvariable=self.agent_profile_var,
                     values=profile_labels(), state="readonly",
                     width=24).pack(side="left", padx=(0, 8))
        ttk.Button(profile_row, text="Применить профиль",
                   command=self.apply_agent_profile).pack(side="left")
        tk.Label(profile_row, text="Роль доступа", bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(16, 6))
        from .roles import ROLE_LABELS, normalize_role, role_labels

        self.access_role_var = tk.StringVar(
            value=ROLE_LABELS.get(normalize_role(self.app.settings.access_role),
                                  role_labels()[0]))
        ttk.Combobox(profile_row, textvariable=self.access_role_var,
                     values=role_labels(), state="readonly",
                     width=28).pack(side="left", padx=(0, 8))
        ttk.Button(profile_row, text="Сохранить роль",
                   command=self.save_access_role).pack(side="left")

        agent_row = tk.Frame(agent_card, bg=C["panel"])
        agent_row.pack(fill="x")
        tk.Label(agent_row, text="Максимум шагов", bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.agent_steps_var = tk.StringVar(
            value=str(self.app.settings.agent_max_steps))
        tk.Entry(agent_row, textvariable=self.agent_steps_var, width=5,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(0, 16))
        tk.Label(agent_row, text="Уровень рассуждений", bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.agent_reasoning_var = tk.StringVar(
            value=self.app.settings.agent_reasoning)
        ttk.Combobox(agent_row, textvariable=self.agent_reasoning_var,
                     values=("off", "low", "medium", "high"),
                     state="readonly", width=8).pack(side="left", padx=(0, 16))
        self.agent_verify_var = tk.BooleanVar(
            value=bool(self.app.settings.agent_verify))
        tk.Checkbutton(agent_row, text="Самопроверка результата",
                       variable=self.agent_verify_var, bg=C["panel"],
                       font=F_BASE).pack(side="left", padx=(0, 10))
        self.agent_subagents_var = tk.BooleanVar(
            value=bool(self.app.settings.agent_subagents))
        tk.Checkbutton(agent_row, text="Подагенты",
                       variable=self.agent_subagents_var, bg=C["panel"],
                       font=F_BASE).pack(side="left")

        tk.Label(agent_card,
                 text="Дополнительные инструкции для агента (системный промпт):",
                 bg=C["panel"], fg=C["muted"], font=F_SMALL).pack(anchor="w",
                                                                  pady=(6, 0))
        self.agent_extra_text = tk.Text(agent_card, height=3, wrap="word",
                                        bd=1, relief="solid", font=F_MONO)
        self.agent_extra_text.pack(fill="x", pady=(2, 6))
        if self.app.settings.agent_system_extra:
            self.agent_extra_text.insert("1.0", self.app.settings.agent_system_extra)
        ttk.Button(agent_card, text="Сохранить настройки агента",
                   style="Accent.TButton", command=self.save_agent).pack(
            anchor="w", pady=(2, 4))
        tk.Label(agent_card,
                 text="Агент видит модель, метрики и обучение (get_model_info, "
                      "get_metrics_history), корректирует обучение на лету "
                      "(set_training_control), планирует (set_plan) и запускает "
                      "подагентов (spawn_subagent). Провайдеры: OpenAI/Codex, "
                      "Claude, Gemini, OpenRouter, Ollama, DeepSeek, Groq, Mistral.",
                 bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w", pady=(2, 0))

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
        appearance_section = Collapsible(self, "Внешний вид")
        appearance_section.pack(fill="x", padx=24, pady=(0, 12))
        appearance_section.set_hint("свернуть/развернуть")
        appearance = appearance_section.body
        self.theme_status = tk.StringVar(
            value="Текущая тема: светлая.")
        tk.Label(appearance, textvariable=self.theme_status, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(anchor="w")
        theme_btns = tk.Frame(appearance, bg=C["panel"])
        theme_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(theme_btns, text="Светлая тема",
                   command=lambda: self.app.toggle_theme("light")).pack(
            side="left")
        ttk.Button(theme_btns, text="Тёмная тема",
                   command=lambda: self.app.toggle_theme("dark")).pack(
            side="left", padx=8)
        tk.Label(appearance,
                 text="Тема применяется сразу и сохраняется при перезапуске.",
                 bg=C["panel"], fg=C["muted"], font=F_SMALL).pack(
            anchor="w", pady=(4, 0))

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
        from .theme import current_theme

        self.theme_status.set("Текущая тема: " + ("тёмная"
                              if current_theme() == "dark" else "светлая") + ".")

    # ------------------------------------------------------------- handlers
    def _on_provider_selected(self, _event=None):
        from .llm_providers import provider_id_by_label, provider_info

        info = provider_info(provider_id_by_label(self.provider_var.get()))
        if info.base_url:
            self.mentor_vars["mentor_base_url"].set(info.base_url)
        if info.model_hint and not self.model_var.get().strip():
            self.model_var.set(info.model_hint)

    def _collect_mentor(self):
        from .llm_providers import provider_id_by_label, provider_info

        provider_id = provider_id_by_label(self.provider_var.get().strip())
        info = provider_info(provider_id)
        self.app.settings.llm_provider = info.id
        self.app.settings.mentor_provider = info.label
        self.app.settings.mentor_base_url = (
            self.mentor_vars["mentor_base_url"].get().strip() or info.base_url)
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

    def save_access_role(self):
        from .roles import role_id_by_label

        self.app.settings.access_role = role_id_by_label(
            self.access_role_var.get())
        self.app.save_settings()
        messagebox.showinfo(
            "Роль доступа",
            f"Роль сохранена: «{self.access_role_var.get()}».\n"
            "Гостевой режим делает агента и инструменты только для чтения.",
            parent=self)

    def apply_agent_profile(self):
        from .agent_profiles import apply_profile, profile_id_by_label

        profile = apply_profile(self.app.settings,
                                profile_id_by_label(self.agent_profile_var.get()))
        self.agent_steps_var.set(str(self.app.settings.agent_max_steps))
        self.agent_reasoning_var.set(self.app.settings.agent_reasoning)
        self.agent_verify_var.set(bool(self.app.settings.agent_verify))
        self.agent_subagents_var.set(bool(self.app.settings.agent_subagents))
        self.agent_extra_text.delete("1.0", "end")
        self.agent_extra_text.insert("1.0", self.app.settings.agent_system_extra)
        self.app.save_settings()
        messagebox.showinfo(
            "ИИ-агент",
            f"Профиль «{profile.label}» применён и сохранён.",
            parent=self)

    def save_agent(self):
        try:
            steps = int(self.agent_steps_var.get())
            if not 4 <= steps <= 40:
                raise ValueError("Максимум шагов: от 4 до 40.")
        except ValueError as exc:
            messagebox.showerror("ИИ-агент", str(exc) or "Шаги должны быть числом.",
                                 parent=self)
            return
        reasoning = self.agent_reasoning_var.get().strip().lower()
        if reasoning not in {"off", "low", "medium", "high"}:
            reasoning = "medium"
        from .agent_profiles import profile_id_by_label

        self.app.settings.agent_profile = profile_id_by_label(
            self.agent_profile_var.get())
        self.app.settings.agent_max_steps = steps
        self.app.settings.agent_reasoning = reasoning
        self.app.settings.agent_verify = bool(self.agent_verify_var.get())
        self.app.settings.agent_subagents = bool(self.agent_subagents_var.get())
        self.app.settings.agent_system_extra = self.agent_extra_text.get(
            "1.0", "end").strip()[:2000]
        self.app.save_settings()
        messagebox.showinfo("ИИ-агент", "Настройки агента сохранены.", parent=self)

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
