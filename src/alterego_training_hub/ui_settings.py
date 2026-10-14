"""Settings page: mentor provider, model list, API keys, folders."""
from __future__ import annotations
from .i18n import t

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
            t('Настройки'),
            t('Подключение ИИ-наставника, ключи API и папки. Ключи хранятся только в системном хранилище учётных данных и не попадают в файлы проекта.'),
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        # Mentor provider
        mentor_section = Collapsible(self, t('ИИ-наставник (OpenAI-совместимый API)'))
        mentor_section.pack(fill="x", padx=24, pady=(0, 12))
        mentor_section.set_hint(t('свернуть/развернуть'))
        mentor_card = mentor_section.body
        mentor_card.columnconfigure(1, weight=1)

        self.mentor_vars: dict[str, tk.StringVar] = {}
        # Provider picker: id -> label from the shared registry.
        from .llm_providers import provider_info, provider_labels

        tk.Label(mentor_card, text=t('Провайдер ИИ'), bg=C["panel"],
                 font=F_BASE).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        current_label = provider_info(self.app.settings.llm_provider).label
        self.provider_var = tk.StringVar(value=current_label)
        self.provider_combo = ttk.Combobox(
            mentor_card, textvariable=self.provider_var,
            values=provider_labels(), state="readonly", font=F_BASE)
        self.provider_combo.grid(row=0, column=1, sticky="ew", pady=5)
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_selected)

        tk.Label(mentor_card, text=t('Базовый URL'), bg=C["panel"],
                 font=F_BASE).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        base_value = self.app.settings.mentor_base_url \
            or provider_info(self.app.settings.llm_provider).base_url
        self.mentor_vars["mentor_base_url"] = tk.StringVar(value=base_value)
        tk.Entry(mentor_card, textvariable=self.mentor_vars["mentor_base_url"],
                 bd=1, relief="solid", font=F_BASE).grid(
            row=1, column=1, sticky="ew", pady=5)

        tk.Label(mentor_card, text=t('ID модели'), bg=C["panel"], font=F_BASE).grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=5)
        self.model_var = tk.StringVar(value=self.app.settings.mentor_model)
        self.model_combo = ttk.Combobox(mentor_card, textvariable=self.model_var,
                                        font=F_BASE)
        self.model_combo.grid(row=2, column=1, sticky="ew", pady=5)

        gen_row = tk.Frame(mentor_card, bg=C["panel"])
        gen_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=5)
        tk.Label(gen_row, text=t('Температура'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.temp_var = tk.StringVar(value=str(self.app.settings.mentor_temperature))
        tk.Entry(gen_row, textvariable=self.temp_var, width=6, bd=1, relief="solid",
                 font=F_BASE).pack(side="left", padx=(0, 16))
        tk.Label(gen_row, text=t('Макс. токенов ответа'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.tokens_var = tk.StringVar(value=str(self.app.settings.mentor_max_tokens))
        tk.Entry(gen_row, textvariable=self.tokens_var, width=8, bd=1, relief="solid",
                 font=F_BASE).pack(side="left")

        key_row = tk.Frame(mentor_card, bg=C["panel"])
        key_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=5)
        tk.Label(key_row, text=t('API-ключ'), bg=C["panel"], font=F_BASE).pack(side="left",
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
        ttk.Button(btn_row, text=t('Сохранить настройки и ключ'),
                   style="Accent.TButton", command=self.save_mentor).pack(side="left")
        ttk.Button(btn_row, text=t('Получить список моделей'),
                   command=self.fetch_models).pack(side="left", padx=8)
        ttk.Button(btn_row, text=t('Проверить соединение'),
                   command=self.test_mentor).pack(side="left", padx=8)
        ttk.Button(btn_row, text=t('Удалить сохранённый ключ'),
                   style="Danger.TButton", command=self.delete_mentor_key).pack(side="left",
                                                                                padx=8)

        # Agent behaviour
        agent_section = Collapsible(self, t('ИИ-агент: точность и возможности'))
        agent_section.pack(fill="x", padx=24, pady=(0, 12))
        agent_section.set_hint(t('свернуть/развернуть'))
        agent_card = agent_section.body
        agent_card.columnconfigure(1, weight=1)

        profile_row = tk.Frame(agent_card, bg=C["panel"])
        profile_row.pack(fill="x")
        tk.Label(profile_row, text=t('Профиль агента'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        from .agent_profiles import profile_info, profile_labels

        current_profile = profile_info(self.app.settings.agent_profile)
        self.agent_profile_var = tk.StringVar(value=current_profile.label)
        ttk.Combobox(profile_row, textvariable=self.agent_profile_var,
                     values=profile_labels(), state="readonly",
                     width=24).pack(side="left", padx=(0, 8))
        ttk.Button(profile_row, text=t('Применить профиль'),
                   command=self.apply_agent_profile).pack(side="left")
        tk.Label(profile_row, text=t('Роль доступа'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(16, 6))
        from .roles import ROLE_LABELS, normalize_role, role_labels

        self.access_role_var = tk.StringVar(
            value=ROLE_LABELS.get(normalize_role(self.app.settings.access_role),
                                  role_labels()[0]))
        ttk.Combobox(profile_row, textvariable=self.access_role_var,
                     values=role_labels(), state="readonly",
                     width=28).pack(side="left", padx=(0, 8))
        ttk.Button(profile_row, text=t('Сохранить роль'),
                   command=self.save_access_role).pack(side="left")

        agent_row = tk.Frame(agent_card, bg=C["panel"])
        agent_row.pack(fill="x")
        tk.Label(agent_row, text=t('Максимум шагов'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.agent_steps_var = tk.StringVar(
            value=str(self.app.settings.agent_max_steps))
        tk.Entry(agent_row, textvariable=self.agent_steps_var, width=5,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(0, 16))
        tk.Label(agent_row, text=t('Уровень рассуждений'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.agent_reasoning_var = tk.StringVar(
            value=self.app.settings.agent_reasoning)
        ttk.Combobox(agent_row, textvariable=self.agent_reasoning_var,
                     values=("off", "low", "medium", "high"),
                     state="readonly", width=8).pack(side="left", padx=(0, 16))
        self.agent_verify_var = tk.BooleanVar(
            value=bool(self.app.settings.agent_verify))
        tk.Checkbutton(agent_row, text=t('Самопроверка результата'),
                       variable=self.agent_verify_var, bg=C["panel"],
                       font=F_BASE).pack(side="left", padx=(0, 10))
        self.agent_subagents_var = tk.BooleanVar(
            value=bool(self.app.settings.agent_subagents))
        tk.Checkbutton(agent_row, text=t('Подагенты'),
                       variable=self.agent_subagents_var, bg=C["panel"],
                       font=F_BASE).pack(side="left")

        tk.Label(agent_card,
                 text=t('Дополнительные инструкции для агента (системный промпт):'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL).pack(anchor="w",
                                                                  pady=(6, 0))
        self.agent_extra_text = tk.Text(agent_card, height=3, wrap="word",
                                        bd=1, relief="solid", font=F_MONO)
        self.agent_extra_text.pack(fill="x", pady=(2, 6))
        if self.app.settings.agent_system_extra:
            self.agent_extra_text.insert("1.0", self.app.settings.agent_system_extra)
        ttk.Button(agent_card, text=t('Сохранить настройки агента'),
                   style="Accent.TButton", command=self.save_agent).pack(
            anchor="w", pady=(2, 4))
        tk.Label(agent_card,
                 text=t('Агент видит модель, метрики и обучение (get_model_info, get_metrics_history), корректирует обучение на лету (set_training_control), планирует (set_plan) и запускает подагентов (spawn_subagent). Провайдеры: OpenAI/Codex, Claude, Gemini, OpenRouter, Ollama, DeepSeek, Groq, Mistral.'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w", pady=(2, 0))

        # Keys for cloud
        # ------------------------------------------------------- platform
        from .hotkeys import DEFAULT_HOTKEYS, resolve_hotkeys
        from .i18n import LANGUAGES, current_language, t as _t

        platform_section = Collapsible(self, _t("platform.title"))
        platform_section.pack(fill="x", padx=24, pady=(0, 12))
        platform_section.set_hint(t('свернуть/развернуть'))
        platform_card = platform_section.body

        row = tk.Frame(platform_card, bg=C["panel"])
        row.pack(fill="x", pady=(2, 0))
        tk.Label(row, text=_t("platform.language"), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        self.language_var = tk.StringVar(
            value=LANGUAGES.get(current_language(), LANGUAGES["ru"]))
        ttk.Combobox(row, textvariable=self.language_var,
                     values=list(LANGUAGES.values()), state="readonly",
                     width=12).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="OK", width=4,
                   command=self.save_language).pack(side="left", padx=(0, 16))
        tk.Label(row, text=_t("platform.layout"), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 6))
        from .layouts import layout_names

        self.layout_var = tk.StringVar(
            value=self.app.settings.active_layout or "code")
        ttk.Combobox(row, textvariable=self.layout_var, values=layout_names(),
                     state="readonly", width=14).pack(side="left", padx=(0, 8))
        ttk.Button(row, text=_t("platform.apply_layout"),
                   command=self.apply_layout_preset).pack(side="left", padx=(0, 8))
        ttk.Button(row, text=_t("platform.save_layout"),
                   command=self.save_current_layout).pack(side="left")
        tk.Label(platform_card, text=_t("platform.language_note"),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL).pack(anchor="w",
                                                                  pady=(4, 0))

        keys_platform = Collapsible(self, _t("platform.keys_title"))
        keys_platform.pack(fill="x", padx=24, pady=(0, 12))
        keys_platform.set_hint(t('свернуть/развернуть'))
        keys_card2 = keys_platform.body
        self.hotkey_vars: dict[str, tk.StringVar] = {}
        bindings = resolve_hotkeys(self.app.settings.hotkeys)
        grid = tk.Frame(keys_card2, bg=C["panel"])
        grid.pack(fill="x")
        for index, (action_id, action) in enumerate(DEFAULT_HOTKEYS.items()):
            column = 0 if index < 10 else 1
            row_index = index if index < 10 else index - 10
            tk.Label(grid, text=action.label, bg=C["panel"], font=F_SMALL).grid(
                row=row_index, column=column * 2, sticky="w",
                padx=(0 if column == 0 else 16, 6), pady=1)
            var = tk.StringVar(value=bindings.get(action_id,
                                                  action.default_key))
            self.hotkey_vars[action_id] = var
            tk.Entry(grid, textvariable=var, width=18, bd=1, relief="solid",
                     font=F_MONO).grid(row=row_index, column=column * 2 + 1,
                                       sticky="w", pady=1)
        hk_bar = tk.Frame(keys_card2, bg=C["panel"])
        hk_bar.pack(fill="x", pady=(6, 0))
        ttk.Button(hk_bar, text=_t("platform.save_hotkeys"),
                   style="Accent.TButton",
                   command=self.save_hotkeys).pack(side="left")
        ttk.Button(hk_bar, text=_t("platform.reset_hotkeys"),
                   command=self.reset_hotkeys).pack(side="left", padx=8)
        tk.Label(keys_card2, text=_t("platform.hotkeys_hint"), bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w", pady=(4, 0))

        tk.Label(keys_card2, text=_t("platform.plugins"), bg=C["panel"],
                 font=F_BASE).pack(anchor="w", pady=(8, 2))
        self.plugins_var = tk.StringVar(value="")
        tk.Label(keys_card2, textvariable=self.plugins_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")
        ttk.Button(keys_card2, text=_t("platform.reload_plugins"),
                   command=self.reload_plugins).pack(anchor="w", pady=(4, 2))
        plugin_row = tk.Frame(keys_card2, bg=C["panel"])
        plugin_row.pack(fill="x", pady=(2, 2))
        self.plugin_choice = ttk.Combobox(plugin_row, state="readonly",
                                          width=44)
        self.plugin_choice.pack(side="left")
        ttk.Button(plugin_row, text=t('Доверять плагину'),
                   command=lambda: self.set_selected_plugin_trust(True)
                   ).pack(side="left", padx=6)
        ttk.Button(plugin_row, text=t('Не доверять'),
                   command=lambda: self.set_selected_plugin_trust(False)
                   ).pack(side="left")
        catalog_row = tk.Frame(keys_card2, bg=C["panel"])
        catalog_row.pack(fill="x", pady=(2, 2))
        tk.Label(catalog_row, text=t('Каталог плагинов'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 8))
        self.catalog_choice = ttk.Combobox(catalog_row, state="readonly",
                                           width=36)
        self.catalog_choice.pack(side="left")
        ttk.Button(catalog_row, text=t('Установить из каталога'),
                   command=self.install_from_catalog).pack(side="left", padx=6)
        ttk.Button(catalog_row, text=t('Удалить плагин'),
                   style="Danger.TButton",
                   command=self.uninstall_selected_plugin).pack(side="left")
        self._refresh_plugins_label()
        self._refresh_catalog_combo()

        sync_section = Collapsible(self, t('Синхронизация настроек'))
        sync_section.pack(fill="x", padx=24, pady=(0, 12))
        sync_card = sync_section.body
        tk.Label(sync_card,
                 text=t('Синхронизация настроек между машинами: экспортируйте файл или укажите общую папку (облако). Секреты (API-ключи) не экспортируются — они остаются в системном хранилище.'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")
        sync_row = tk.Frame(sync_card, bg=C["panel"])
        sync_row.pack(fill="x", pady=(6, 2))
        tk.Label(sync_row, text=t('Папка синхронизации (облако)'),
                 bg=C["panel"], font=F_BASE).pack(side="left", padx=(0, 8))
        self.sync_dir_var = tk.StringVar(
            value=getattr(self.app.settings, "settings_sync_dir", "") or "")
        tk.Entry(sync_row, textvariable=self.sync_dir_var, bd=1, relief="solid",
                 font=F_BASE, width=48).pack(side="left")
        ttk.Button(sync_row, text=t('Выбрать…'),
                   command=self.browse_sync_dir).pack(side="left", padx=6)
        sync_btns = tk.Frame(sync_card, bg=C["panel"])
        sync_btns.pack(fill="x", pady=(4, 2))
        ttk.Button(sync_btns, text=t('Выгрузить…'),
                   command=self.export_settings_dialog).pack(side="left")
        ttk.Button(sync_btns, text=t('Загрузить…'),
                   command=self.import_settings_dialog).pack(side="left", padx=6)
        ttk.Button(sync_btns, text=t('Отправить в папку'),
                   command=self.push_settings_sync).pack(side="left", padx=6)
        ttk.Button(sync_btns, text=t('Получить из папки'),
                   command=self.pull_settings_sync).pack(side="left", padx=6)
        self.sync_status_var = tk.StringVar(value="")
        tk.Label(sync_card, textvariable=self.sync_status_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")
        tk.Label(sync_card,
                 text=t('Перетащите полосу сверху панели к краю окна, чтобы закрепить её.'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w", pady=(2, 0))

        keys_section = Collapsible(self, t('Ключи облачных сервисов'))
        keys_section.pack(fill="x", padx=24, pady=(0, 12))
        keys_card = keys_section.body
        row = tk.Frame(keys_card, bg=C["panel"])
        row.pack(fill="x")
        tk.Label(row, text=t('RunPod API-ключ'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.runpod_key_var = tk.StringVar()
        tk.Entry(row, textvariable=self.runpod_key_var, show="•", bd=1, relief="solid",
                 font=F_BASE, width=40).pack(side="left")
        self.runpod_secret_status = tk.StringVar(
            value=self._secret_status("runpod_api_key"))
        tk.Label(row, textvariable=self.runpod_secret_status, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left", padx=10)
        ttk.Button(row, text=t('Сохранить ключ'), command=self.save_runpod_key).pack(
            side="left")
        ttk.Button(row, text=t('Удалить ключ'), style="Danger.TButton",
                   command=self.delete_runpod_key).pack(side="left", padx=8)

        # Folders
        folders_section = Collapsible(self, t('Папки'))
        folders_section.pack(fill="x", padx=24, pady=(0, 12))
        folders_card = folders_section.body
        folders_card.columnconfigure(1, weight=1)

        self.workspace_var = tk.StringVar(value=self.app.settings.workspace_path)
        self.library_var = tk.StringVar(value=self.app.settings.model_library_path)
        for row, (label, var, command) in enumerate([
            (t('Рабочая папка (ИИ + обучение)'), self.workspace_var, self.pick_workspace),
            (t('Библиотека моделей (можно облако)'), self.library_var, self.pick_library),
        ]):
            tk.Label(folders_card, text=label, bg=C["panel"], font=F_BASE).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            tk.Entry(folders_card, textvariable=var, bd=1, relief="solid",
                     font=F_BASE).grid(row=row, column=1, sticky="ew", pady=5)
            ttk.Button(folders_card, text=t('Обзор…'), command=command).grid(
                row=row, column=2, padx=(8, 0), pady=5)
        ttk.Button(folders_card, text=t('Сохранить папки'),
                   command=self.save_folders).grid(row=2, column=1, sticky="w", pady=8)

        # Diagnostics
        appearance_section = Collapsible(self, t('Внешний вид'))
        appearance_section.pack(fill="x", padx=24, pady=(0, 12))
        appearance_section.set_hint(t('свернуть/развернуть'))
        appearance = appearance_section.body
        self.theme_status = tk.StringVar(
            value=t('Текущая тема: светлая.'))
        tk.Label(appearance, textvariable=self.theme_status, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(anchor="w")
        theme_btns = tk.Frame(appearance, bg=C["panel"])
        theme_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(theme_btns, text=t('Светлая тема'),
                   command=lambda: self.app.toggle_theme("light")).pack(
            side="left")
        ttk.Button(theme_btns, text=t('Тёмная тема'),
                   command=lambda: self.app.toggle_theme("dark")).pack(
            side="left", padx=8)
        tk.Label(appearance,
                 text=t('Тема применяется сразу и сохраняется при перезапуске.'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL).pack(
            anchor="w", pady=(4, 0))

        diag_section = Collapsible(self, t('Диагностика и логи'))
        diag_section.pack(fill="x", padx=24, pady=(0, 12))
        diag_section.set_hint(t('свернуть/развернуть'))
        diag = diag_section.body
        self.diag_status = tk.StringVar(value=t('Проверка окружения: Python, хранилище ключей, SSH, Git, папки, диск.'))
        tk.Label(diag, textvariable=self.diag_status, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL, wraplength=860, justify="left").pack(anchor="w")
        btns = tk.Frame(diag, bg=C["panel"])
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text=t('Запустить проверку'), style="Accent.TButton",
                   command=self.run_check).pack(side="left")
        ttk.Button(btns, text=t('Скопировать отчёт'),
                   command=self.copy_diag).pack(side="left", padx=8)
        ttk.Button(btns, text=t('Показать лог ошибок'),
                   command=self.show_log).pack(side="left", padx=8)
        self.diag_text = tk.Text(diag, height=8, wrap="word", state="disabled",
                                 bd=1, relief="solid", font=F_MONO)
        self.diag_text.pack(fill="x", pady=(8, 2))

        tk.Label(
            self,
            text=t('Ключи хранятся через системный диспетчер учётных данных (keyring). Настройки — в профиле пользователя, без секретов.'),
            bg=C["bg"], fg=C["muted"], font=F_SMALL,
        ).pack(anchor="w", padx=24, pady=(0, 14))

    # -------------------------------------------------------------- helpers
    def _secret_status(self, name: str) -> str:
        try:
            return t('Ключ сохранён') if self.app.secrets.get(name) else t('Ключ не сохранён')
        except Exception:
            return t('Хранилище ключей недоступно')

    def run_check(self):
        self.diag_status.set(t('Выполняется проверка…'))

        def done(results):
            summary = diagnostics_summary(results)
            self._last_diag = diagnostics_text(results)
            set_text(self.diag_text, self._last_diag)
            self.diag_status.set(
                t('Проверка завершена: ошибок — {v1}, предупреждений — {v3}.').format(v1=summary['errors'], v3=summary['warnings']))

        self.app.start_async(t('Диагностика'),
                             lambda: run_diagnostics(self.app.settings,
                                                     self.app.secrets),
                             done)

    def copy_diag(self):
        text = self._last_diag or self.diag_text.get("1.0", "end")
        if not text.strip():
            messagebox.showinfo(t('Диагностика'), t('Сначала запустите проверку.'),
                                parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def show_log(self):
        tail = tail_log(12000)
        set_text(self.diag_text, tail or t('Лог пуст.'))
        self.diag_status.set(t('Файл лога: {v1}').format(v1=log_file()))

    def on_show(self):
        self.mentor_secret_status.set(self._secret_status("mentor_api_key"))
        self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
        from .theme import current_theme

        self.theme_status.set(t('Текущая тема: ') + (t('тёмная')
                              if current_theme() == "dark" else t('светлая')) + ".")

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
            raise MentorError(t('Температура и максимум токенов должны быть числами.')) from None
        if not 0 <= temperature <= 2:
            raise MentorError(t('Температура должна быть от 0 до 2.'))
        if not 1 <= max_tokens <= 8000:
            raise MentorError(t('Максимум токенов: от 1 до 8000.'))
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
                t('ИИ-наставник'),
                t('Настройки сохранены. Ключ (если указан) сохранён в системном хранилище учётных данных.'),
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror(t('ИИ-наставник'), str(exc), parent=self)

    # --------------------------------------------------------- platform
    def save_language(self):
        from .i18n import LANGUAGES

        selected = self.language_var.get()
        lang = next((code for code, label in LANGUAGES.items()
                     if label == selected), "ru")
        self.app.apply_language(lang)
        messagebox.showinfo(t('Язык'),
                            t('Язык применён сразу.'), parent=self)

    # ------------------------------------------------------ settings sync
    def browse_sync_dir(self):
        from tkinter import filedialog

        directory = filedialog.askdirectory() or ""
        if directory:
            self.sync_dir_var.set(directory)
            self.app.settings.settings_sync_dir = directory
            self.app.save_settings()

    def export_settings_dialog(self):
        from tkinter import filedialog

        from .settings_sync import SettingsSyncError, export_settings

        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            file = export_settings(path, self.app.settings)
        except SettingsSyncError as exc:
            messagebox.showerror(t('Настройки'), str(exc), parent=self)
            return
        self.sync_status_var.set(t('Настройки выгружены: ') + str(file))

    def import_settings_dialog(self):
        from tkinter import filedialog

        from .i18n import current_language
        from .settings_sync import SettingsSyncError, apply_bundle, import_bundle

        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            raw = import_bundle(path)
            changed = apply_bundle(self.app.settings, raw)
            self.app.save_settings()
        except SettingsSyncError as exc:
            messagebox.showerror(t('Настройки'), str(exc), parent=self)
            return
        self.sync_status_var.set(t('Настройки загружены и применены.')
                                 + " " + t('Изменённых полей: ')
                                 + str(len(changed)))
        wanted = self.app.settings.ui_language
        if wanted and wanted != current_language():
            self.app.apply_language(wanted)

    def push_settings_sync(self):
        from .settings_sync import SettingsSyncError, push

        try:
            push(self.app.settings, self.sync_dir_var.get().strip())
            self.app.save_settings()
        except SettingsSyncError as exc:
            messagebox.showerror(t('Настройки'), str(exc), parent=self)
            return
        self.sync_status_var.set(
            t('Настройки отправлены в папку синхронизации.'))

    def pull_settings_sync(self):
        from .settings_sync import SettingsSyncError, pull

        try:
            applied, changed = pull(self.app.settings,
                                    self.sync_dir_var.get().strip())
            self.app.save_settings()
        except SettingsSyncError as exc:
            messagebox.showerror(t('Настройки'), str(exc), parent=self)
            return
        if not applied:
            self.sync_status_var.set(
                t('Изменений нет — настройки уже актуальны.'))
        else:
            self.sync_status_var.set(t('Изменённых полей: ')
                                     + str(len(changed)))

    def apply_layout_preset(self):
        from .layouts import layout_info

        try:
            state = layout_info(self.layout_var.get())
        except Exception as exc:
            messagebox.showerror(t('Раскладка'), str(exc), parent=self)
            return
        self.app.apply_layout(state)
        self.app.settings.active_layout = self.layout_var.get()
        self.app.save_settings()
        messagebox.showinfo(t('Раскладка'),
                            t('Применена раскладка «{v1}».').format(v1=self.layout_var.get()),
                            parent=self)

    def save_current_layout(self):
        from .layouts import save_layout

        name = (self.layout_var.get() or "custom").strip() or "custom"
        path = Path(self.app.model_registry().library_dir) / \
            f"layout-{name}.json"
        try:
            save_layout(path, self.app.current_layout())
        except Exception as exc:
            messagebox.showerror(t('Раскладка'), str(exc), parent=self)
            return
        messagebox.showinfo(t('Раскладка'), t('Текущая раскладка сохранена: {path}').format(path=path),
                            parent=self)

    def save_hotkeys(self):
        from .hotkeys import HotkeyError, detect_conflicts, resolve_hotkeys, \
            save_hotkeys

        try:
            raw = {action_id: var.get().strip()
                   for action_id, var in self.hotkey_vars.items()}
            changes = save_hotkeys(raw)
        except HotkeyError as exc:
            messagebox.showerror(t('Горячие клавиши'), str(exc), parent=self)
            return
        self.app.settings.hotkeys = changes
        self.app.save_settings()
        self.app.rebind_hotkeys()
        conflicts = detect_conflicts(resolve_hotkeys(changes))
        note = (t('\nКонфликты: {conflicts}').format(conflicts=conflicts) if conflicts else "")
        messagebox.showinfo(t('Горячие клавиши'),
                            t('Сохранено изменённых комбинаций: {v1}. Применено сразу.{note}').format(v1=len(changes), note=note),
                            parent=self)

    def reset_hotkeys(self):
        from .hotkeys import DEFAULT_HOTKEYS

        for action_id, var in self.hotkey_vars.items():
            var.set(DEFAULT_HOTKEYS[action_id].default_key)
        self.app.settings.hotkeys = {}
        self.app.save_settings()
        self.app.rebind_hotkeys()
        messagebox.showinfo(t('Горячие клавиши'),
                            t('Возвращены комбинации по умолчанию.'), parent=self)

    def reload_plugins(self):
        self.app._plugin_list = self.app.plugins.load_all()
        self._refresh_plugins_label()

    def _refresh_plugins_label(self):
        lines = []
        choices = []
        for plugin in getattr(self.app, "_plugin_list", []):
            mark = "✓" if plugin.ok and plugin.enabled else (
                "⚠" if plugin.ok else "✗")
            trust = t('доверенный') if plugin.trusted else t('песочница')
            tool_names = ", ".join(tool.name for tool in plugin.tools) or "—"
            lines.append(f"{mark} {plugin.name} v{plugin.version} "
                         f"[{tool_names}] ({trust})"
                         + (f" — {plugin.error}" if plugin.error else ""))
            choices.append(f"{plugin.id} — {plugin.name} v{plugin.version}")
        directory = self.app.plugins.plugins_dir
        self.plugins_var.set(
            "\n".join(lines) if lines
            else t('Папка {directory} пуста — положите туда plugin.py с словарём PLUGIN (см. README).').format(directory=directory))
        if hasattr(self, "plugin_choice"):
            self.plugin_choice.configure(values=choices)
            self._plugin_choices = [plugin.id for plugin
                                    in getattr(self.app, "_plugin_list", [])]

    def _refresh_catalog_combo(self):
        from .plugin_catalog import BUILTIN_CATALOG

        self._catalog_entries = list(BUILTIN_CATALOG)
        labels = [f"{entry.name} v{entry.version} — {entry.description}"
                  for entry in self._catalog_entries]
        self.catalog_choice.configure(values=labels)
        if labels:
            self.catalog_choice.current(0)

    def _combo_index(self, combo) -> int:
        try:
            index = combo.current()
        except Exception:  # noqa: BLE001
            index = None
        return index if isinstance(index, int) else -1

    def _selected_plugin_id(self) -> str:
        index = self._combo_index(self.plugin_choice)
        ids = getattr(self, "_plugin_choices", [])
        if not (0 <= index < len(ids)):
            messagebox.showinfo(t('Плагины'),
                                t('Выберите плагин.'), parent=self)
            return ""
        return ids[index]

    def set_selected_plugin_trust(self, trusted: bool):
        plugin_id = self._selected_plugin_id()
        if not plugin_id:
            return
        self.app.plugins.set_trust(plugin_id, trusted)
        self.reload_plugins()
        self.app.set_status(f"{plugin_id}: "
                           + (t('доверенный') if trusted else t('песочница')))

    def install_from_catalog(self):
        from .plugin_catalog import CatalogError, install_entry

        index = self._combo_index(self.catalog_choice)
        entries = getattr(self, "_catalog_entries", [])
        if not (0 <= index < len(entries)):
            messagebox.showinfo(t('Каталог плагинов'),
                                t('Выберите запись каталога.'), parent=self)
            return
        entry = entries[index]
        try:
            target = install_entry(entry, self.app.plugins.plugins_dir)
        except CatalogError as exc:
            messagebox.showerror(t('Каталог плагинов'), str(exc), parent=self)
            return
        self.reload_plugins()
        self.app.set_status(t('Плагин установлен: ') + str(target))

    def uninstall_selected_plugin(self):
        from .plugin_catalog import uninstall

        plugin_id = self._selected_plugin_id()
        if not plugin_id:
            return
        if not messagebox.askyesno(t('Удалить плагин'),
                                   t('Удалить «{v1}»?').format(v1=plugin_id),
                                   parent=self):
            return
        removed = uninstall(plugin_id, self.app.plugins.plugins_dir)
        self.reload_plugins()
        self.app.set_status((t('Плагин удалён: ') if removed
                              else t('Не удалось удалить: ')) + plugin_id)

    def save_access_role(self):
        from .roles import role_id_by_label

        self.app.settings.access_role = role_id_by_label(
            self.access_role_var.get())
        self.app.save_settings()
        messagebox.showinfo(
            t('Роль доступа'),
            t('Роль сохранена: «{v1}».\nГостевой режим делает агента и инструменты только для чтения.').format(v1=self.access_role_var.get()),
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
            t('ИИ-агент'),
            t('Профиль «{v1}» применён и сохранён.').format(v1=profile.label),
            parent=self)

    def save_agent(self):
        try:
            steps = int(self.agent_steps_var.get())
            if not 4 <= steps <= 40:
                raise ValueError(t('Максимум шагов: от 4 до 40.'))
        except ValueError as exc:
            messagebox.showerror(t('ИИ-агент'), str(exc) or t('Шаги должны быть числом.'),
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
        messagebox.showinfo(t('ИИ-агент'), t('Настройки агента сохранены.'), parent=self)

    def fetch_models(self):
        try:
            self._collect_mentor()
            self.app.save_settings()
            client = self.app.mentor_client()
        except Exception as exc:
            messagebox.showerror(t('ИИ-наставник'), str(exc), parent=self)
            return

        def done(models):
            self.model_combo.configure(values=models)
            if self.model_var.get() not in models and models:
                self.model_var.set(models[0])
            messagebox.showinfo(t('Модели'), t('Получено моделей: {v1}').format(v1=len(models)), parent=self)

        self.app.start_async(t('Получение списка моделей'), client.list_models, done)

    def test_mentor(self):
        try:
            self._collect_mentor()
            self.app.save_settings()
            client = self.app.mentor_client()
        except Exception as exc:
            messagebox.showerror(t('ИИ-наставник'), str(exc), parent=self)
            return
        if not messagebox.askyesno(
            t('Отправить проверочный запрос'),
            t('Тестовый запрос будет отправлен внешнему API и может расходовать кредиты провайдера. Продолжить?'),
            parent=self,
        ):
            return

        def done(reply):
            messagebox.showinfo(
                t('Соединение работает'),
                t('Модель: {v1}\n\n{v3}').format(v1=reply.model, v3=reply.text[:500]),
                parent=self,
            )

        self.app.start_async(
            t('Проверка соединения с наставником'),
            lambda: client.ask(t('Ответь одним словом: готов.'), max_tokens=20),
            done,
        )

    def delete_mentor_key(self):
        if not messagebox.askyesno(t('Удалить ключ'), t('Удалить сохранённый ключ наставника?'),
                                   parent=self):
            return
        try:
            self.app.secrets.delete("mentor_api_key")
            self.mentor_secret_status.set(self._secret_status("mentor_api_key"))
            messagebox.showinfo(t('ИИ-наставник'), t('Ключ удалён.'), parent=self)
        except Exception as exc:
            messagebox.showerror(t('ИИ-наставник'), str(exc), parent=self)

    def save_runpod_key(self):
        key = self.runpod_key_var.get().strip()
        if not key:
            messagebox.showinfo("RunPod", t('Введите API-ключ для сохранения.'), parent=self)
            return
        try:
            self.app.secrets.set("runpod_api_key", key)
            self.runpod_key_var.set("")
            self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
            messagebox.showinfo("RunPod", t('Ключ сохранён в системном хранилище.'),
                                parent=self)
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)

    def delete_runpod_key(self):
        if not messagebox.askyesno(t('Удалить ключ'), t('Удалить ключ RunPod?'), parent=self):
            return
        try:
            self.app.secrets.delete("runpod_api_key")
            self.runpod_secret_status.set(self._secret_status("runpod_api_key"))
        except Exception as exc:
            messagebox.showerror("RunPod", str(exc), parent=self)

    def pick_workspace(self):
        path = filedialog.askdirectory(title=t('Рабочая папка'))
        if path:
            self.workspace_var.set(path)

    def pick_library(self):
        path = filedialog.askdirectory(title=t('Библиотека моделей'))
        if path:
            self.library_var.set(path)

    def save_folders(self):
        for var in (self.workspace_var, self.library_var):
            raw = var.get().strip()
            if raw and not Path(raw).expanduser().is_dir():
                messagebox.showerror(t('Папки'), t('Папка не существует: {raw}').format(raw=raw), parent=self)
                return
        self.app.settings.workspace_path = self.workspace_var.get().strip()
        self.app.settings.model_library_path = self.library_var.get().strip()
        self.app.save_settings()
        messagebox.showinfo(t('Папки'), t('Папки сохранены.'), parent=self)
        chat = self.app.pages.get("chat")
        if chat is not None:
            chat.on_show()
