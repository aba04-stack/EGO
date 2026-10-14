"""Model dashboard: model card, training progress, mentor assessment, actions."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from .i18n import t
from .metrics import brief as metrics_brief
from .metrics import parse_log
from .ui_common import (
    F_BASE,
    F_BOLD,
    F_SMALL,
    C,
    Collapsible,
    card,
    draw_line_chart,
    page_header,
)


class ModelDashboardPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        header = page_header(
            self,
            t('Модель и прогресс'),
            t('Сводка по выбранной модели: прогресс обучения с графиком метрик, оценка наставника (что хорошо / что плохо / риски) и журнал действий.'),
        )
        header.pack(fill="x", padx=24, pady=(18, 10))

        bar = tk.Frame(self, bg=C["bg"])
        bar.pack(fill="x", padx=24, pady=(0, 10))
        tk.Label(bar, text=t('Модель'), bg=C["bg"], font=F_BOLD).pack(side="left",
                                                                   padx=(0, 8))
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(bar, textvariable=self.model_var,
                                        state="readonly", width=36)
        self.model_combo.pack(side="left")
        self.model_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self.select_model())
        ttk.Button(bar, text=t('Обновить'), command=self.refresh).pack(side="left", padx=8)
        ttk.Button(bar, text=t('Оценка наставника'), style="Accent.TButton",
                   command=self.request_assessment).pack(side="left", padx=8)
        ttk.Button(bar, text=t('Подобрать параметры'),
                   command=self.suggest_fixes).pack(side="left", padx=8)
        ttk.Button(bar, text=t('Экспорт отчёта'),
                   command=self.export_report).pack(side="left", padx=8)
        ttk.Button(bar, text=t('Открыть чат'),
                   command=lambda: self.app.show_page("chat")).pack(side="left")

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(0, 14))
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)

        # Model card
        info = card(body, t('Карточка модели'))
        info.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 10))
        self.info_text = tk.Text(info, height=10, wrap="word", state="disabled",
                                 bd=0, bg=C["panel"], fg=C["text"], font=F_BASE)
        self.info_text.pack(fill="both", expand=True)

        # Progress card
        progress = card(body, t('Прогресс обучения'))
        progress.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 10))
        self.progress_var = tk.StringVar(value=t('Нет данных'))
        tk.Label(progress, textvariable=self.progress_var, bg=C["panel"], fg=C["text"],
                 font=F_BASE, wraplength=520, justify="left").pack(anchor="w")
        self.progressbar = ttk.Progressbar(progress, maximum=1.0, value=0.0)
        self.progressbar.pack(fill="x", pady=(6, 4))
        self.anomaly_var = tk.StringVar(value="")
        tk.Label(progress, textvariable=self.anomaly_var, bg=C["panel"],
                 fg=C["warning"], font=F_SMALL, wraplength=520, justify="left").pack(
            anchor="w")
        self.watchdog_var = tk.StringVar(value="")
        tk.Label(progress, textvariable=self.watchdog_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=520, justify="left").pack(
            anchor="w")
        self.chart = tk.Canvas(progress, width=520, height=190, bg=C["panel"],
                               highlightthickness=0)
        self.chart.pack(fill="both", expand=True, pady=(6, 0))
        self._poll_running = False

        # Assessment card
        assess = card(body, t('Оценка наставника'))
        assess.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        top = tk.Frame(assess, bg=C["panel"])
        top.pack(fill="x")
        self.score_var = tk.StringVar(value=t('оценки пока нет'))
        tk.Label(top, textvariable=self.score_var, bg=C["panel"], fg=C["accent"],
                 font=("Segoe UI", 13, "bold")).pack(side="left")
        self.assess_stamp = tk.StringVar(value="")
        tk.Label(top, textvariable=self.assess_stamp, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="right")
        columns = tk.Frame(assess, bg=C["panel"])
        columns.pack(fill="both", expand=True, pady=(6, 0))
        self.lists: dict[str, tk.Text] = {}
        for idx, (key, title, color) in enumerate([
            ("strengths", t('Что хорошо'), C["success"]),
            ("weaknesses", t('Что плохо'), C["danger"]),
            ("risks", t('Риски'), C["warning"]),
            ("recommendations", t('Рекомендации'), C["accent"]),
        ]):
            frame = tk.Frame(columns, bg=C["panel"])
            frame.pack(side="left", fill="both", expand=True, padx=(0 if idx == 0 else 6, 0))
            tk.Label(frame, text=title, bg=C["panel"], fg=color,
                     font=F_BOLD).pack(anchor="w")
            text = tk.Text(frame, height=5, wrap="word", state="disabled", bd=1,
                           relief="solid", font=F_SMALL)
            text.pack(fill="both", expand=True)
            self.lists[key] = text
        tk.Label(assess, text=t('Рассуждение'), bg=C["panel"], fg=C["text"],
                 font=F_BOLD).pack(anchor="w", pady=(8, 2))
        self.reasoning_text = tk.Text(assess, height=4, wrap="word", state="disabled",
                                      bd=1, relief="solid", font=F_BASE)
        self.reasoning_text.pack(fill="both", expand=True)

        # Activity card
        activity = card(body, t('Действия — журнал активности'))
        activity.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 0))
        self.activity_text = tk.Text(activity, height=6, wrap="word", state="disabled",
                                     bd=0, bg=C["panel"], fg=C["text"], font=F_SMALL)
        self.activity_text.pack(fill="both", expand=True)

        # ---- Night watch: overnight agent duty with a morning sum --------
        night = Collapsible(self, t('Ночное дежурство'))
        night.pack(fill="x", padx=24, pady=(0, 12))
        night_card = night.body
        tk.Label(night_card,
                 text=t('Агент периодически проверяет обучение ночью и к утру готовит итог: состояние, риски и одно действие.'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")
        night_row = tk.Frame(night_card, bg=C["panel"])
        night_row.pack(fill="x", pady=(6, 2))
        self.night_enabled_var = tk.BooleanVar(
            value=bool(getattr(self.app.settings, "night_watch_enabled", False)))
        tk.Checkbutton(night_row, text=t('Включить дежурство'),
                       variable=self.night_enabled_var, bg=C["panel"],
                       font=F_BASE, command=self.save_night_watch).pack(
            side="left")
        tk.Label(night_row, text=t('Интервал (мин)'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(12, 4))
        self.night_interval_var = tk.StringVar(
            value=str(getattr(self.app.settings, "night_watch_interval", 30)
                      or 30))
        tk.Entry(night_row, textvariable=self.night_interval_var, width=6,
                 bd=1, relief="solid", font=F_BASE).pack(side="left")
        ttk.Button(night_row, text=t('Проверить сейчас'),
                   command=self.run_night_check_now).pack(side="left", padx=8)
        ttk.Button(night_row, text=t('Итог утром'),
                   command=self.show_morning_report).pack(side="left")
        self.night_status_var = tk.StringVar(value="")
        tk.Label(night_card, textvariable=self.night_status_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")

        # ---- Прозрачность ЛЛМ и генерации при обучении (этап 26) ---------
        trans = Collapsible(self, t('Прозрачность и генерации'))
        trans.pack(fill="x", padx=24, pady=(0, 12))
        trans_card = trans.body
        tk.Label(trans_card,
                 text=t('Протокол «Мысль → Действие → Ответ» раскрывает, почему агент ответил так; «Критик» вторым проходом сверяет ответ с действиями и метриками; сэмплы показывают, что модель реально генерирует при обучении.'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")
        trans_row = tk.Frame(trans_card, bg=C["panel"])
        trans_row.pack(fill="x", pady=(6, 2))
        self.thought_var = tk.BooleanVar(
            value=bool(getattr(self.app.settings, "thought_protocol", True)))
        tk.Checkbutton(trans_row, text=t('Протокол мыслей'),
                       variable=self.thought_var, bg=C["panel"], font=F_BASE,
                       command=self.save_transparency).pack(side="left")
        self.critic_var = tk.BooleanVar(
            value=bool(getattr(self.app.settings, "critic_enabled", False)))
        tk.Checkbutton(trans_row, text=t('Критик ответов'),
                       variable=self.critic_var, bg=C["panel"], font=F_BASE,
                       command=self.save_transparency).pack(side="left", padx=(12, 0))
        ttk.Button(trans_row, text=t('Сэмплы генерации'),
                   command=self.show_samples).pack(side="left", padx=8)
        ttk.Button(trans_row, text=t('Бенчмарк агента'),
                   command=self.run_agent_benchmark).pack(side="left")
        ttk.Button(trans_row, text=t('Бенчмарк модели'),
                   command=self.run_live_benchmark).pack(side="left", padx=6)
        self.samples_var = tk.StringVar(value="")
        tk.Label(trans_card, textvariable=self.samples_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")

        # ---- Мастер «Своя ЛЛМ» (этап 27) --------------------------------
        wiz = Collapsible(self, t('Мастер «Своя ЛЛМ»'))
        wiz.pack(fill="x", padx=24, pady=(0, 12))
        wiz_card = wiz.body
        tk.Label(wiz_card,
                 text=t('Путь от своих данных до обученной модели: выберите путь и пресет, укажите датасет — мастер проверит данные, посчитает GPU/часы/цену до старта и даст рекомендации.'),
                 bg=C["panel"], fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")
        wiz_row = tk.Frame(wiz_card, bg=C["panel"])
        wiz_row.pack(fill="x", pady=(6, 2))
        from .model_recipes import PRESETS, RECIPES

        self._wizard_recipes = list(RECIPES)
        self._wizard_presets = list(PRESETS)
        tk.Label(wiz_row, text=t('Путь'), bg=C["panel"], font=F_BASE).pack(side="left")
        self.recipe_combo = ttk.Combobox(
            wiz_row, state="readonly", width=30,
            values=[r.name for r in RECIPES])
        self.recipe_combo.pack(side="left", padx=(4, 10))
        self.recipe_combo.current(0)
        tk.Label(wiz_row, text=t('Пресет'), bg=C["panel"], font=F_BASE).pack(side="left")
        self.preset_combo = ttk.Combobox(
            wiz_row, state="readonly", width=22,
            values=[p.name for p in PRESETS])
        self.preset_combo.pack(side="left", padx=(4, 0))
        self.preset_combo.current(0)
        wiz_row2 = tk.Frame(wiz_card, bg=C["panel"])
        wiz_row2.pack(fill="x", pady=(4, 2))
        tk.Label(wiz_row2, text=t('Датасет (файл)'), bg=C["panel"],
                 font=F_BASE).pack(side="left")
        self.wizard_dataset_var = tk.StringVar(value="")
        tk.Entry(wiz_row2, textvariable=self.wizard_dataset_var, width=52,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(4, 8))
        wiz_lora = tk.Frame(wiz_card, bg=C["panel"])
        wiz_lora.pack(fill="x", pady=(4, 2))
        tk.Label(wiz_lora, text=t('LoRA r'), bg=C["panel"],
                 font=F_BASE).pack(side="left")
        self.wizard_lora_r_var = tk.StringVar(value="16")
        tk.Entry(wiz_lora, textvariable=self.wizard_lora_r_var, width=5,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(4, 8))
        tk.Label(wiz_lora, text=t('alpha'), bg=C["panel"],
                 font=F_BASE).pack(side="left")
        self.wizard_lora_alpha_var = tk.StringVar(value="32")
        tk.Entry(wiz_lora, textvariable=self.wizard_lora_alpha_var, width=5,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(4, 8))
        self.wizard_qlora_var = tk.BooleanVar(value=False)
        tk.Checkbutton(wiz_lora, text=t('QLoRA (4-bit)'),
                       variable=self.wizard_qlora_var, bg=C["panel"],
                       font=F_BASE).pack(side="left", padx=(0, 8))
        tk.Label(wiz_lora, text=t('Grad accum'), bg=C["panel"],
                 font=F_BASE).pack(side="left")
        self.wizard_grad_accum_var = tk.StringVar(value="1")
        tk.Entry(wiz_lora, textvariable=self.wizard_grad_accum_var, width=5,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(4, 8))
        tk.Label(wiz_lora, text=t('GPU (шт)'), bg=C["panel"],
                 font=F_BASE).pack(side="left")
        self.wizard_gpus_var = tk.StringVar(value="1")
        tk.Entry(wiz_lora, textvariable=self.wizard_gpus_var, width=5,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(4, 0))
        wiz_row3 = tk.Frame(wiz_card, bg=C["panel"])
        wiz_row3.pack(fill="x", pady=(4, 2))
        ttk.Button(wiz_row3, text=t('Рассчитать план'), style="Accent.TButton",
                   command=self.show_wizard_plan).pack(side="left")
        ttk.Button(wiz_row3, text=t('Обучить токенизатор'),
                   command=self.train_tokenizer_now).pack(side="left", padx=6)
        ttk.Button(wiz_row3, text=t('Снять baseline'),
                   command=self.save_wizard_baseline).pack(side="left")
        ttk.Button(wiz_row3, text=t('Сравнить до/после'),
                   command=self.show_before_after).pack(side="left", padx=6)
        ttk.Button(wiz_row3, text=t('Создать скрипт обучения'),
                   command=self.create_train_script).pack(side="left")
        ttk.Button(wiz_row3, text=t('Smoke-прогон'),
                   command=self.run_smoke_check).pack(side="left", padx=6)
        self.wizard_var = tk.StringVar(value="")
        tk.Label(wiz_card, textvariable=self.wizard_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, wraplength=860,
                 justify="left").pack(anchor="w")

    def _wizard_choice(self, combo, items, fallback=0):
        try:
            index = combo.current()
        except Exception:
            index = fallback
        if not isinstance(index, int) or index < 0 or index >= len(items):
            index = fallback
        return items[index]

    def wizard_audit(self):
        from .data_audit import audit_rows
        from .datasets import read_rows

        path = self.wizard_dataset_var.get().strip()
        rows = []
        if path:
            from pathlib import Path

            file = Path(path)
            if file.is_file():
                fmt = file.suffix.lstrip(".").lower() or "txt"
                if fmt not in ("jsonl", "json", "csv", "tsv", "txt"):
                    fmt = "txt"
                try:
                    rows = read_rows(file, fmt, limit=5000)
                    if fmt == "txt":
                        rows = [line for line in
                                file.read_text(encoding="utf-8", errors="replace").splitlines()]
                except Exception:
                    rows = []
        return audit_rows(rows)

    def _wizard_plan_obj(self):
        from .wizard_plan import build_plan

        recipe = self._wizard_choice(self.recipe_combo, self._wizard_recipes)
        preset = self._wizard_choice(self.preset_combo, self._wizard_presets)
        plan = build_plan(path=recipe.path, recipe_name=recipe.name,
                          preset=preset, audit=self.wizard_audit(),
                          max_hourly=float(getattr(
                              self.app.settings, "runpod_max_gpu_hourly_usd", 0.5) or 0.5))
        return recipe, preset, plan

    def wizard_plan_text(self) -> str:
        return self._wizard_plan_obj()[2].render()

    @staticmethod
    def _wizard_int(var, fallback: int) -> int:
        try:
            return int(str(var.get()).strip())
        except (TypeError, ValueError):
            return fallback

    def train_script_config(self):
        from .train_script import ScriptConfig

        recipe, preset, plan = self._wizard_plan_obj()
        advice = plan.advice
        return ScriptConfig(
            path=recipe.path, recipe_name=recipe.name, preset=preset,
            dataset_path=self.wizard_dataset_var.get().strip(),
            base_model=str(getattr(self.app.settings, "mentor_model", "") or ""),
            lr=advice.lr, batch=advice.batch, epochs=advice.epochs,
            seq_len=advice.seq_len, warmup_pct=advice.warmup_pct,
            lora_r=self._wizard_int(self.wizard_lora_r_var, 16),
            lora_alpha=self._wizard_int(self.wizard_lora_alpha_var, 32),
            qlora=bool(self.wizard_qlora_var.get()),
            grad_accum=self._wizard_int(self.wizard_grad_accum_var, 1),
            gpus=self._wizard_int(self.wizard_gpus_var, 1))

    def create_train_script(self):
        """Генерация train_llm.py из плана мастера в рабочую папку."""
        from pathlib import Path
        from tkinter import messagebox

        from .train_script import generate_script, render_plan_note

        cfg = self.train_script_config()
        root = self.app.workspace_root()
        target_dir = Path(root) if root is not None else (
            self.app.model_registry().library_dir / "scripts")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "train_llm.py"
        target.write_text(generate_script(cfg), encoding="utf-8")
        self.app.settings.training_command = "python train_llm.py"
        self.app.save_settings()
        note = render_plan_note(cfg)
        self.wizard_var.set(t('Скрипт сохранён: ') + str(target))
        messagebox.showinfo(t('Скрипт обучения'), note + "\n\n" + str(target),
                            parent=self)
        return target

    def show_wizard_plan(self):
        from tkinter import messagebox

        text = self.wizard_plan_text()
        self.wizard_var.set(text.splitlines()[0] if text else "")
        messagebox.showinfo(t('План «Своя ЛЛМ»'), text, parent=self)

    def train_tokenizer_now(self):
        from pathlib import Path

        from .tokenizer_train import compression_stats, train_on_text

        path = self.wizard_dataset_var.get().strip()
        text = ""
        if path and Path(path).is_file():
            text = Path(path).read_text(encoding="utf-8", errors="replace")[:500_000]
        if not text.strip():
            self.wizard_var.set(t('Укажите текстовый датасет для токенизатора.'))
            return
        tok = train_on_text(text, vocab_size=800)
        target = (self.app.model_registry().library_dir / "tokenizers"
                  / "wizard-bpe.json")
        tok.save(target)
        stats = compression_stats(tok, text[:10000])
        self.wizard_var.set(
            t('Токенизатор сохранён: {v1} · словарь {v3}, {v5} симв/токен').format(
                v1=target.name, v3=stats["vocab_size"],
                v5=stats["chars_per_token"]))

    def _wizard_baseline_path(self):
        return self.app.model_registry().library_dir / "wizard-baseline.log"

    def save_wizard_baseline(self):
        target = self._wizard_baseline_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            tail = self.app.training.tail(20000)
        except Exception:
            tail = ""
        target.write_text(tail or "", encoding="utf-8")
        self.wizard_var.set(t('Baseline снят: ') + target.name)

    def before_after_text(self) -> str:
        from .wizard_plan import compare_before_after

        target = self._wizard_baseline_path()
        before = target.read_text(encoding="utf-8") if target.is_file() else ""
        try:
            after = self.app.training.tail(20000)
        except Exception:
            after = ""
        return compare_before_after(before, after or "").render()

    def show_before_after(self):
        from tkinter import messagebox

        text = self.before_after_text()
        self.wizard_var.set(text.splitlines()[0] if text else "")
        messagebox.showinfo(t('До / после'), text, parent=self)

    def agent_benchmark_text(self) -> str:
        from .agent_bench import run_benchmark

        return run_benchmark().render()

    def run_agent_benchmark(self):
        from tkinter import messagebox

        def done(text):
            self.samples_var.set(text.splitlines()[0] if text else "")
            messagebox.showinfo(t('Бенчмарк агента'), text, parent=self)

        self.app.start_async(t('Бенчмарк агента'),
                             self.agent_benchmark_text, done)

    def smoke_text(self) -> str:
        from pathlib import Path

        from .smoke_run import smoke_script

        cfg = self.train_script_config()
        root = self.app.workspace_root()
        target_dir = Path(root) if root is not None else (
            self.app.model_registry().library_dir / "scripts")
        return smoke_script(target_dir / "train_llm.py",
                            dataset_path=cfg.dataset_path).render()

    def run_smoke_check(self):
        from tkinter import messagebox

        def done(text):
            self.wizard_var.set(text.splitlines()[0] if text else "")
            messagebox.showinfo(t('Smoke-прогон скрипта'), text, parent=self)

        self.app.start_async(t('Smoke-прогон'), self.smoke_text, done)

    def live_benchmark_text(self) -> str:
        from .live_bench import run_live_benchmark
        from .mentor import MentorError

        try:
            mentor = self.app.mentor_client()
        except MentorError as exc:
            return str(exc)
        return run_live_benchmark(mentor).render()

    def run_live_benchmark(self):
        from tkinter import messagebox

        def done(text):
            self.samples_var.set(text.splitlines()[0] if text else "")
            messagebox.showinfo(t('Бенчмарк модели'), text, parent=self)

        self.app.start_async(t('Бенчмарк модели'),
                             self.live_benchmark_text, done)

    def save_transparency(self):
        self.app.settings.thought_protocol = bool(self.thought_var.get())
        self.app.settings.critic_enabled = bool(self.critic_var.get())
        self.app.save_settings()
        self.samples_var.set(t('Сохранено: протокол — {v1}, критик — {v2}').format(
            v1=t('вкл') if self.thought_var.get() else t('выкл'),
            v2=t('вкл') if self.critic_var.get() else t('выкл')))

    def samples_text(self) -> str:
        from .gen_preview import format_samples, parse_samples

        try:
            tail = self.app.training.tail(20000)
        except Exception:
            tail = ""
        samples = parse_samples(tail or "")
        if not samples:
            return t('Сэмплов в логе обучения пока нет. Добавьте в команду обучения печать строк вида {"sample": {"step": 100, "prompt": "…", "text": "…"}} или блоков ### sample @100 — и они появятся здесь.')
        return format_samples(samples)

    def show_samples(self):
        from tkinter import messagebox

        text = self.samples_text()
        self.samples_var.set(text.splitlines()[0] if text else "")
        messagebox.showinfo(t('Сэмплы генерации'), text, parent=self)

    def save_night_watch(self):
        enabled = bool(self.night_enabled_var.get())
        try:
            interval = max(5, min(1440, int(self.night_interval_var.get())))
        except (TypeError, ValueError):
            interval = 30
            self.night_interval_var.set("30")
        self.app.settings.night_watch_enabled = enabled
        self.app.settings.night_watch_interval = interval
        self.app.save_settings()
        self.night_status_var.set(
            t('Включено · интервал {v1} мин').format(v1=interval) if enabled
            else t('Выключено'))

    def run_night_check_now(self):
        self.save_night_watch()
        self.app.start_async(
            t('Ночная проверка'),
            lambda: self.app.run_night_check(),
            lambda entry: self.night_status_var.set(
                t('Последнее наблюдение:') + " " + entry.line()))

    def show_morning_report(self):
        from tkinter import messagebox

        messagebox.showinfo(t('Итог утром'), self.app.morning_report_text(),
                            parent=self)

    # -------------------------------------------------------------- refresh
    def on_show(self):
        self.refresh()
        self._schedule_poll()

    def _load_model_entries(self):
        try:
            return self.app.model_registry().load()
        except Exception:
            return []

    def refresh(self):
        try:
            self._refresh_inner()
        except Exception as exc:
            self.app.set_status(t('Не удалось обновить дашборд: {exc}').format(exc=exc))

    def _refresh_inner(self):
        entries = self._load_model_entries()
        labels = [f"{entry.name}  ·  {entry.kind}" for entry in entries]
        self.model_combo.configure(values=labels)
        active_id = self.app.settings.active_model_id
        active = next((e for e in entries if e.id == active_id), None)
        if active is None and entries:
            active = entries[0]
            self.app.settings.active_model_id = active.id
            self.app.save_settings()
        if active is not None and labels:
            self.model_var.set(f"{active.name}  ·  {active.kind}")
        else:
            self.model_var.set("")

        self._render_info(active)
        self._render_progress()
        self._render_assessment()
        self._render_activity()

    def select_model(self):
        title = self.model_var.get()
        for entry in self._load_model_entries():
            if f"{entry.name}  ·  {entry.kind}" == title:
                self.app.settings.active_model_id = entry.id
                self.app.save_settings()
                self.refresh()
                return

    def _render_info(self, entry):
        from .ui_common import set_text

        if entry is None:
            set_text(self.info_text, t('В каталоге пока нет моделей.\n\nДобавьте модель на странице «Каталог моделей».'))
            return
        stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(entry.updated_at))
        metrics = "\n".join(f"  {k}: {v}" for k, v in entry.metrics.items()) or "  —"
        set_text(self.info_text, (
            t('Название: {v1}\nТип: {v3}\nПуть / URI: {v5}\nAPI model id: {v7}\nURL инференса: {v9}\nОбновлено: {stamp}\nМетрики:\n{metrics}\nЗаметки: {v15}').format(v1=entry.name, v3=entry.kind, v5=entry.location, v7=entry.model_id or '—', v9=entry.base_url or '—', stamp=stamp, metrics=metrics, v15=entry.notes or '—')
        ))

    def _render_progress(self):

        status = self.app.training.status()
        summary = parse_log(self.app.training.tail())
        state = t('выполняется') if status.running else (
            t('остановлено (код {v1})').format(v1=status.returncode) if status.returncode is not None
            else t('не запускалось'))
        line = t('Состояние: {state}\nКоманда: {v3}\nМетрики: {v5}').format(state=state, v3=status.command or '—', v5=metrics_brief(summary))
        self.progress_var.set(line)
        ratio = summary.progress_ratio or 0.0
        try:
            self.progressbar.configure(value=ratio)
        except Exception:
            pass
        if summary.anomalies:
            self.anomaly_var.set("⚠ " + "\n⚠ ".join(summary.anomalies))
        else:
            self.anomaly_var.set("")

        series = {}
        if summary.primary_key:
            series[summary.primary_key] = summary.series(summary.primary_key)
        for key in ("acc", "val_acc", "val_loss", "train_loss"):
            if key in summary.last and key not in series:
                series[key] = summary.series(key)
        draw_line_chart(self.chart, series)

        # Watchdog: same detectors the mentor sees, right under the chart.
        try:
            from .watchdog import detect_issues

            report_lines = [
                issue.line() for issue in detect_issues(
                    summary, running=status.running)]
            self.watchdog_var.set("\n".join(report_lines[:4]))
        except Exception:
            self.watchdog_var.set("")

    def _schedule_poll(self):
        """Refresh the chart while the page is open (live training view)."""
        if self._poll_running:
            return
        self._poll_running = True
        self._poll_once()

    def _poll_once(self):
        try:
            self.refresh()
        except Exception:
            pass
        try:
            self.after(5000, self._poll_once)
        except Exception:
            self._poll_running = False

    def _render_assessment(self):
        from .report import ModelReport
        from .ui_common import set_text

        report = self.app.reports.latest() or ModelReport()
        if report.is_empty():
            self.score_var.set(t('Оценки пока нет — нажмите «Оценка наставника»'))
            self.assess_stamp.set("")
        else:
            score = f"{report.score:g}/10" if report.score is not None else t('без оценки')
            self.score_var.set(t('Оценка: {score}').format(score=score))
            stamp = time.strftime("%d.%m %H:%M", time.localtime(report.created_at))
            self.assess_stamp.set(t('обновлено {stamp}').format(stamp=stamp))
        for key, text in self.lists.items():
            items = getattr(report, key)
            set_text(text, "\n".join(f"• {item}" for item in items) or "—")
        set_text(self.reasoning_text, report.reasoning or "—")

    def _render_activity(self):
        from .ui_common import set_text

        events = self.app.activity.recent(12)
        if not events:
            set_text(self.activity_text,
                     t('Журнал пуст. Здесь появятся действия наставника, запуски обучения и правки файлов.'))
            return
        icons = {"training": "▶", "mentor_tool": "»", "file_edit": "✎",
                 "report": "★", "system": "·"}
        lines = []
        for event in events:
            icon = icons.get(event.kind, "·")
            lines.append(f"{event.stamp()}  {icon}  {event.summary}")
        set_text(self.activity_text, "\n".join(lines))

    # ------------------------------------------------------------- actions
    def export_report(self):
        """Save the full training report as Markdown/HTML (print → PDF)."""
        from tkinter import filedialog, messagebox

        from .report_export import save_report

        path = filedialog.asksaveasfilename(
            title=t('Экспорт отчёта'), defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("HTML", "*.html")])
        if not path:
            return
        fmt = path.rsplit(".", 1)[-1].lower()
        try:
            exported = save_report(path, self.app.build_report_context(),
                                   fmt=fmt)
        except Exception as exc:
            messagebox.showerror(t('Отчёт'), str(exc), parent=self)
            return
        note = ("\n" + exported.note) if exported.note else ""
        messagebox.showinfo(t('Отчёт'), t('Сохранено: {v1}{note}').format(v1=exported.path, note=note),
                            parent=self)

    def suggest_fixes(self):
        """Propose hyperparameter changes from metrics and apply on demand."""
        from tkinter import messagebox

        from .hparam_tuning import suggest_fixes as _suggest
        from .training import read_control, write_control

        root = self.app.workspace_root()
        if root is None:
            messagebox.showinfo(t('Подбор параметров'),
                                t('Сначала выберите рабочую папку.'), parent=self)
            return
        summary = parse_log(self.app.training.tail())
        control = read_control(root)
        suggestions = _suggest(summary, control)
        if not suggestions:
            messagebox.showinfo(t('Подбор параметров'),
                                t('Нет предложений — метрики в норме.'), parent=self)
            return
        text = "\n".join(suggestion.line() for suggestion in suggestions)
        if not messagebox.askyesno(
            t('Подбор параметров'),
            t('Предлагаемые изменения:\n\n') + text
            + t('\n\nПрименить их к обучению (control.json)?'), parent=self):
            return
        patch = dict(control)
        for suggestion in suggestions:
            patch[suggestion.param] = suggestion.value
        write_control(root, patch)
        self.app.activity.log("tuning", t('Применены параметры:\n') + text)
        self.refresh()

    def request_assessment(self):
        prompt = self.app.assessment_prompt()
        self.app.show_page("chat")
        chat = self.app.pages["chat"]
        chat.send_preset(prompt)
