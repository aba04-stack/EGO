"""Playground page: probe models and compare answers side by side (A/B)."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .mentor import MentorError
from .playground import PlaygroundClient, PlaygroundStore
from .ui_common import C, F_BASE, F_SMALL, Collapsible, card, page_header, set_text


class PlaygroundPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.store = PlaygroundStore()
        self._build()

    def _build(self):
        header = page_header(
            self,
            "Playground",
            "Проверка моделей на тестовых промптах и сравнение A/B: один промпт — "
            "два ответа, латентность и параметры. Ключ берётся из системного "
            "хранилища (тот же, что у наставника).",
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        setup_section = Collapsible(self, "Модели и параметры")
        setup_section.pack(fill="x", padx=24, pady=(0, 12))
        setup_section.set_hint("свернуть/развернуть")
        setup = setup_section.body
        row1 = tk.Frame(setup, bg=C["panel"])
        row1.pack(fill="x", pady=(2, 4))
        tk.Label(row1, text="Модель A", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.model_a = tk.StringVar()
        self.combo_a = ttk.Combobox(row1, textvariable=self.model_a, width=44)
        self.combo_a.pack(side="left", padx=(0, 16))
        tk.Label(row1, text="Модель B (A/B)", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.model_b = tk.StringVar()
        self.combo_b = ttk.Combobox(row1, textvariable=self.model_b, width=44)
        self.combo_b.pack(side="left")
        ttk.Button(row1, text="Обновить список",
                   command=self.refresh_models).pack(side="left", padx=8)

        row2 = tk.Frame(setup, bg=C["panel"])
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="System", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.system_var = tk.StringVar(value="Ты полезный ассистент.")
        tk.Entry(row2, textvariable=self.system_var, bd=1, relief="solid",
                 font=F_BASE).pack(side="left", fill="x", expand=True, padx=(0, 16))
        tk.Label(row2, text="Температура", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.temp_var = tk.StringVar(value="0.7")
        tk.Entry(row2, textvariable=self.temp_var, width=6, bd=1, relief="solid",
                 font=F_BASE).pack(side="left", padx=(0, 16))
        tk.Label(row2, text="Макс. токенов", bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.tokens_var = tk.StringVar(value="512")
        tk.Entry(row2, textvariable=self.tokens_var, width=8, bd=1, relief="solid",
                 font=F_BASE).pack(side="left")

        prompt_card = card(self, "Промпт")
        prompt_card.pack(fill="x", padx=24, pady=(0, 12))
        self.prompt = tk.Text(prompt_card, height=3, wrap="word", font=F_BASE,
                              bd=1, relief="solid")
        self.prompt.pack(fill="x")
        btns = tk.Frame(prompt_card, bg=C["panel"])
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Запустить", style="Accent.TButton",
                   command=self.run_single).pack(side="left")
        ttk.Button(btns, text="Сравнить A/B",
                   command=self.run_compare).pack(side="left", padx=8)
        ttk.Button(btns, text="История",
                   command=self.show_history).pack(side="left", padx=8)

        outputs = tk.Frame(self, bg=C["bg"])
        outputs.pack(fill="both", expand=True, padx=24, pady=(0, 14))
        self.out_a = self._output_panel(outputs, "Ответ A")
        self.out_b = self._output_panel(outputs, "Ответ B (сравнение)")

    def _output_panel(self, parent, title):
        frame = card(parent, title)
        frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
        label = tk.StringVar(value="готово к запуску")
        tk.Label(frame, textvariable=label, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(anchor="w")
        text = tk.Text(frame, wrap="word", state="disabled", bd=1, relief="solid",
                       font=F_BASE)
        text.pack(fill="both", expand=True, pady=(4, 0))
        return label, text

    # ------------------------------------------------------------- models
    def on_show(self):
        self.refresh_models()

    def _model_choices(self) -> dict[str, tuple[str, str]]:
        """label -> (base_url, model_id)"""
        choices: dict[str, tuple[str, str]] = {}
        settings = self.app.settings
        if settings.mentor_base_url and settings.mentor_model:
            choices[f"Текущий наставник: {settings.mentor_model}"] = (
                settings.mentor_base_url, settings.mentor_model)
        for entry in self.app.model_registry().load():
            if entry.base_url and entry.model_id:
                choices[f"{entry.name} ({entry.model_id})"] = (
                    entry.base_url, entry.model_id)
        return choices

    def refresh_models(self):
        choices = list(self._model_choices())
        self.combo_a.configure(values=choices)
        self.combo_b.configure(values=["— без сравнения —"] + choices)
        if choices and not self.model_a.get():
            self.model_a.set(choices[0])
        if not self.model_b.get():
            self.model_b.set("— без сравнения —")

    def _client_for(self, label: str) -> PlaygroundClient:
        choices = self._model_choices()
        if label not in choices:
            raise MentorError(
                "Выберите модель с настроенным URL инференса (строка в "
                "«Каталоге моделей» или текущий наставник).")
        base_url, model = choices[label]
        key = self.app.secrets.get("mentor_api_key")
        if not key:
            raise MentorError("Сохраните API-ключ на странице «Настройки».")
        return PlaygroundClient(base_url, model, key)

    # ------------------------------------------------------------- runners
    def _params(self):
        try:
            temperature = float(self.temp_var.get())
            max_tokens = int(self.tokens_var.get())
        except ValueError:
            raise MentorError("Температура и токены должны быть числами.") from None
        if not 0 <= temperature <= 2:
            raise MentorError("Температура: 0…2.")
        if not 1 <= max_tokens <= 8000:
            raise MentorError("Токены: 1…8000.")
        return temperature, max_tokens

    def run_single(self):
        prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            return
        try:
            client = self._client_for(self.model_a.get())
            temperature, max_tokens = self._params()
        except MentorError as exc:
            messagebox.showerror("Playground", str(exc), parent=self)
            return
        set_text(self.out_b[1], "")
        self.out_b[0].set("—")
        self.out_a[0].set("выполняется…")

        def done(result):
            self._show_result(self.out_a, result)
            self.store.save(result)
            self.app.activity.log("system",
                                  f"Playground: {result.model} ({result.latency_ms} мс)")

        self.app.start_async("Генерация ответа",
                             lambda: client.generate(prompt,
                                                     system=self.system_var.get(),
                                                     temperature=temperature,
                                                     max_tokens=max_tokens),
                             done)

    def run_compare(self):
        prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            return
        try:
            client_a = self._client_for(self.model_a.get())
            client_b = self._client_for(self.model_b.get())
            temperature, max_tokens = self._params()
        except MentorError as exc:
            messagebox.showerror("Playground", str(exc), parent=self)
            return
        self.out_a[0].set("выполняется…")
        self.out_b[0].set("выполняется…")

        def work():
            first = client_a.generate(prompt, system=self.system_var.get(),
                                      temperature=temperature, max_tokens=max_tokens)
            second = client_b.generate(prompt, system=self.system_var.get(),
                                       temperature=temperature, max_tokens=max_tokens)
            return first, second

        def done(pair):
            first, second = pair
            self._show_result(self.out_a, first)
            self._show_result(self.out_b, second)
            self.store.save(first)
            self.store.save(second)
            self.app.activity.log(
                "system",
                f"Playground A/B: {first.model} {first.latency_ms} мс vs "
                f"{second.model} {second.latency_ms} мс")

        self.app.start_async("Сравнение A/B", work, done)

    def _show_result(self, panel, result):
        label, text = panel
        if result.ok():
            label.set(f"{result.model} · {result.latency_ms} мс · "
                      f"T={result.temperature} · {result.max_tokens} ток.")
            set_text(text, result.output)
        else:
            label.set(f"{result.model} · ошибка")
            set_text(text, f"Ошибка: {result.error}")

    def show_history(self):
        items = self.store.recent(10)
        if not items:
            messagebox.showinfo("Playground", "История пуста.", parent=self)
            return
        lines = [
            f"{time.strftime('%d.%m %H:%M', time.localtime(item.created_at))} · "
            f"{item.model} · {item.latency_ms} мс · "
            f"{('ошибка: ' + item.error[:60]) if item.error else item.output[:80]}"
            for item in items
        ]
        set_text(self.out_a[1], "\n\n".join(lines))
        self.out_a[0].set("последние запуски")
