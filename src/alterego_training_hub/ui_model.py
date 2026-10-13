"""Model dashboard: model card, training progress, mentor assessment, actions."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from .metrics import brief as metrics_brief, parse_log
from .ui_common import C, F_BASE, F_BOLD, F_SMALL, card, draw_line_chart, page_header


class ModelDashboardPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        header = page_header(
            self,
            "Модель и прогресс",
            "Сводка по выбранной модели: прогресс обучения с графиком метрик, "
            "оценка наставника (что хорошо / что плохо / риски) и журнал действий.",
        )
        header.pack(fill="x", padx=24, pady=(18, 10))

        bar = tk.Frame(self, bg=C["bg"])
        bar.pack(fill="x", padx=24, pady=(0, 10))
        tk.Label(bar, text="Модель", bg=C["bg"], font=F_BOLD).pack(side="left",
                                                                   padx=(0, 8))
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(bar, textvariable=self.model_var,
                                        state="readonly", width=36)
        self.model_combo.pack(side="left")
        self.model_combo.bind("<<ComboboxSelected>>",
                              lambda _e: self.select_model())
        ttk.Button(bar, text="Обновить", command=self.refresh).pack(side="left", padx=8)
        ttk.Button(bar, text="Оценка наставника", style="Accent.TButton",
                   command=self.request_assessment).pack(side="left", padx=8)
        ttk.Button(bar, text="Подобрать параметры",
                   command=self.suggest_fixes).pack(side="left", padx=8)
        ttk.Button(bar, text="Открыть чат",
                   command=lambda: self.app.show_page("chat")).pack(side="left")

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(0, 14))
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)

        # Model card
        info = card(body, "Карточка модели")
        info.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 10))
        self.info_text = tk.Text(info, height=10, wrap="word", state="disabled",
                                 bd=0, bg=C["panel"], fg=C["text"], font=F_BASE)
        self.info_text.pack(fill="both", expand=True)

        # Progress card
        progress = card(body, "Прогресс обучения")
        progress.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 10))
        self.progress_var = tk.StringVar(value="Нет данных")
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
        assess = card(body, "Оценка наставника")
        assess.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        top = tk.Frame(assess, bg=C["panel"])
        top.pack(fill="x")
        self.score_var = tk.StringVar(value="оценки пока нет")
        tk.Label(top, textvariable=self.score_var, bg=C["panel"], fg=C["accent"],
                 font=("Segoe UI", 13, "bold")).pack(side="left")
        self.assess_stamp = tk.StringVar(value="")
        tk.Label(top, textvariable=self.assess_stamp, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="right")
        columns = tk.Frame(assess, bg=C["panel"])
        columns.pack(fill="both", expand=True, pady=(6, 0))
        self.lists: dict[str, tk.Text] = {}
        for idx, (key, title, color) in enumerate([
            ("strengths", "Что хорошо", C["success"]),
            ("weaknesses", "Что плохо", C["danger"]),
            ("risks", "Риски", C["warning"]),
            ("recommendations", "Рекомендации", C["accent"]),
        ]):
            frame = tk.Frame(columns, bg=C["panel"])
            frame.pack(side="left", fill="both", expand=True, padx=(0 if idx == 0 else 6, 0))
            tk.Label(frame, text=title, bg=C["panel"], fg=color,
                     font=F_BOLD).pack(anchor="w")
            text = tk.Text(frame, height=5, wrap="word", state="disabled", bd=1,
                           relief="solid", font=F_SMALL)
            text.pack(fill="both", expand=True)
            self.lists[key] = text
        tk.Label(assess, text="Рассуждение", bg=C["panel"], fg=C["text"],
                 font=F_BOLD).pack(anchor="w", pady=(8, 2))
        self.reasoning_text = tk.Text(assess, height=4, wrap="word", state="disabled",
                                      bd=1, relief="solid", font=F_BASE)
        self.reasoning_text.pack(fill="both", expand=True)

        # Activity card
        activity = card(body, "Действия — журнал активности")
        activity.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 0))
        self.activity_text = tk.Text(activity, height=6, wrap="word", state="disabled",
                                     bd=0, bg=C["panel"], fg=C["text"], font=F_SMALL)
        self.activity_text.pack(fill="both", expand=True)

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
        except Exception as exc:  # noqa: BLE001 - dashboard must not die on odd data
            self.app.set_status(f"Не удалось обновить дашборд: {exc}")

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
            set_text(self.info_text, "В каталоге пока нет моделей.\n\n"
                                     "Добавьте модель на странице «Каталог моделей».")
            return
        stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(entry.updated_at))
        metrics = "\n".join(f"  {k}: {v}" for k, v in entry.metrics.items()) or "  —"
        set_text(self.info_text, (
            f"Название: {entry.name}\n"
            f"Тип: {entry.kind}\n"
            f"Путь / URI: {entry.location}\n"
            f"API model id: {entry.model_id or '—'}\n"
            f"URL инференса: {entry.base_url or '—'}\n"
            f"Обновлено: {stamp}\n"
            f"Метрики:\n{metrics}\n"
            f"Заметки: {entry.notes or '—'}"
        ))

    def _render_progress(self):

        status = self.app.training.status()
        summary = parse_log(self.app.training.tail())
        state = "выполняется" if status.running else (
            f"остановлено (код {status.returncode})" if status.returncode is not None
            else "не запускалось")
        line = f"Состояние: {state}\nКоманда: {status.command or '—'}\nМетрики: {metrics_brief(summary)}"
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
        except Exception:  # noqa: BLE001 - watchdog must never break the page
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
        except Exception:  # noqa: BLE001
            pass
        try:
            self.after(5000, self._poll_once)
        except Exception:  # noqa: BLE001 - no display server in tests
            self._poll_running = False

    def _render_assessment(self):
        from .report import ModelReport
        from .ui_common import set_text

        report = self.app.reports.latest() or ModelReport()
        if report.is_empty():
            self.score_var.set("Оценки пока нет — нажмите «Оценка наставника»")
            self.assess_stamp.set("")
        else:
            score = f"{report.score:g}/10" if report.score is not None else "без оценки"
            self.score_var.set(f"Оценка: {score}")
            stamp = time.strftime("%d.%m %H:%M", time.localtime(report.created_at))
            self.assess_stamp.set(f"обновлено {stamp}")
        for key, text in self.lists.items():
            items = getattr(report, key)
            set_text(text, "\n".join(f"• {item}" for item in items) or "—")
        set_text(self.reasoning_text, report.reasoning or "—")

    def _render_activity(self):
        from .ui_common import set_text

        events = self.app.activity.recent(12)
        if not events:
            set_text(self.activity_text,
                     "Журнал пуст. Здесь появятся действия наставника, запуски "
                     "обучения и правки файлов.")
            return
        icons = {"training": "▶", "mentor_tool": "»", "file_edit": "✎",
                 "report": "★", "system": "·"}
        lines = []
        for event in events:
            icon = icons.get(event.kind, "·")
            lines.append(f"{event.stamp()}  {icon}  {event.summary}")
        set_text(self.activity_text, "\n".join(lines))

    # ------------------------------------------------------------- actions
    def suggest_fixes(self):
        """Propose hyperparameter changes from metrics and apply on demand."""
        from tkinter import messagebox

        from .hparam_tuning import suggest_fixes as _suggest
        from .training import read_control, write_control

        root = self.app.workspace_root()
        if root is None:
            messagebox.showinfo("Подбор параметров",
                                "Сначала выберите рабочую папку.", parent=self)
            return
        summary = parse_log(self.app.training.tail())
        control = read_control(root)
        suggestions = _suggest(summary, control)
        if not suggestions:
            messagebox.showinfo("Подбор параметров",
                                "Нет предложений — метрики в норме.", parent=self)
            return
        text = "\n".join(suggestion.line() for suggestion in suggestions)
        if not messagebox.askyesno(
            "Подбор параметров",
            "Предлагаемые изменения:\n\n" + text
            + "\n\nПрименить их к обучению (control.json)?", parent=self):
            return
        patch = dict(control)
        for suggestion in suggestions:
            patch[suggestion.param] = suggestion.value
        write_control(root, patch)
        self.app.activity.log("tuning", "Применены параметры:\n" + text)
        self.refresh()

    def request_assessment(self):
        prompt = self.app.assessment_prompt()
        self.app.show_page("chat")
        chat = self.app.pages["chat"]
        chat.send_preset(prompt)
