"""Training page: run training in the workspace, watch progress, involve the mentor."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .metrics import brief as metrics_brief, parse_log
from .training import TrainingError
from .ui_common import C, F_BASE, F_BOLD, F_MONO, F_SMALL, Collapsible, card, draw_line_chart, page_header, set_text


class TrainingPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._current_run_id: str | None = None
        self._build()
        self._tick()

    def _build(self):
        header = page_header(
            self,
            "Обучение",
            "Запуск команды обучения в рабочей папке, живой прогресс и лог. "
            "Наставник может разобрать ошибки и предложить исправления.",
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        run_section = Collapsible(self, "Команда обучения")
        run_section.pack(fill="x", padx=24, pady=(0, 12))
        run_section.set_hint("свернуть/развернуть")
        run_card = run_section.body
        row = tk.Frame(run_card, bg=C["panel"])
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="Команда", bg=C["panel"], font=F_BASE).pack(side="left",
                                                                       padx=(0, 8))
        self.cmd_var = tk.StringVar(value=self.app.settings.training_command)
        tk.Entry(row, textvariable=self.cmd_var, bd=1, relief="solid",
                 font=F_MONO).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_start = ttk.Button(row, text="Запустить", style="Accent.TButton",
                                    command=self.start_training)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row, text="Остановить", style="Danger.TButton",
                                   command=self.stop_training)
        self.btn_stop.pack(side="left", padx=(8, 0))

        opts = tk.Frame(run_card, bg=C["panel"])
        opts.pack(fill="x", pady=(8, 0))
        self.auto_analyze = tk.BooleanVar(value=True)
        tk.Checkbutton(
            opts, text="Автоматически отправлять лог наставнику при ошибке",
            variable=self.auto_analyze, bg=C["panel"], font=F_BASE,
            activebackground=C["panel"],
        ).pack(side="left")
        self.status_var = tk.StringVar(value="Обучение не запущено")
        tk.Label(opts, textvariable=self.status_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="right")

        # Metrics + chart
        metrics_card = card(self, "Прогресс и метрики")
        metrics_card.pack(fill="x", padx=24, pady=(0, 12))
        top = tk.Frame(metrics_card, bg=C["panel"])
        top.pack(fill="x")
        self.metrics_var = tk.StringVar(value="Метрик пока нет")
        tk.Label(top, textvariable=self.metrics_var, bg=C["panel"], fg=C["text"],
                 font=F_BASE, wraplength=760, justify="left").pack(side="left",
                                                                   fill="x", expand=True)
        self.progressbar = ttk.Progressbar(top, maximum=1.0, value=0.0, length=220)
        self.progressbar.pack(side="right", padx=(12, 0))
        self.anomaly_var = tk.StringVar(value="")
        tk.Label(metrics_card, textvariable=self.anomaly_var, bg=C["panel"],
                 fg=C["warning"], font=F_SMALL, wraplength=900, justify="left").pack(
            anchor="w", pady=(4, 0))
        self.chart = tk.Canvas(metrics_card, width=920, height=180, bg=C["panel"],
                               highlightthickness=0)
        self.chart.pack(fill="x", pady=(6, 0))

        log_card = card(self, "Лог")
        log_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        bar = tk.Frame(log_card, bg=C["panel"])
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Обновить лог", command=self.refresh_log).pack(side="left")
        ttk.Button(bar, text="Отправить лог наставнику",
                   command=self.send_log_to_mentor).pack(side="left", padx=8)
        ttk.Button(bar, text="Прогресс наставнику",
                   command=self.send_progress_to_mentor).pack(side="left", padx=8)
        ttk.Button(bar, text="Открыть чат",
                   command=lambda: self.app.show_page("chat")).pack(side="left")

        self.log_text = tk.Text(log_card, wrap="word", state="disabled",
                                bg=C["code_bg"], fg=C["code_fg"], font=F_MONO,
                                bd=0, padx=12, pady=10)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.tag_configure("err", foreground="#f87171")

        runs_box = tk.Frame(log_card, bg=C["panel"], width=260)
        runs_box.pack(side="right", fill="y", padx=(10, 0))
        tk.Label(runs_box, text="История запусков", bg=C["panel"], font=F_BOLD).pack(
            anchor="w")
        self.runs_list = tk.Listbox(runs_box, bg=C["panel"], fg=C["text"],
                                    highlightthickness=0, bd=1, relief="solid",
                                    font=F_SMALL)
        self.runs_list.pack(fill="both", expand=True, pady=(6, 0))
        self.refresh_runs()

    # ------------------------------------------------------------- actions
    def start_training(self):
        command = self.cmd_var.get().strip()
        root = self.app.workspace_root()
        if root is None:
            messagebox.showerror("Обучение",
                                 "Сначала выберите рабочую папку.", parent=self)
            self.app.show_page("workspace")
            return
        self.app.settings.training_command = command
        self.app.save_settings()
        try:
            log_path = self.app.training.start(command, root)
        except TrainingError as exc:
            messagebox.showerror("Обучение", str(exc), parent=self)
            return
        record = self.app.runs.start(command, str(root), log_path)
        self._current_run_id = record.id
        self.app.activity.log("training", f"Обучение запущено: {command}",
                              run_id=record.id, workspace=str(root))
        self.app.set_status("Обучение запущено")
        self.refresh_log()
        self.refresh_runs()

    def stop_training(self):
        try:
            self.app.training.stop()
        except TrainingError as exc:
            messagebox.showinfo("Обучение", str(exc), parent=self)
            return
        self.app.activity.log("training", "Отправлен сигнал остановки")
        self.app.set_status("Отправлен сигнал остановки")

    def refresh_log(self):
        set_text(self.log_text, self.app.training.tail() or "Лог пуст.")
        self.refresh_metrics()

    def refresh_metrics(self):
        summary = parse_log(self.app.training.tail())
        self.metrics_var.set(metrics_brief(summary))
        ratio = summary.progress_ratio or 0.0
        try:
            self.progressbar.configure(value=ratio)
        except Exception:
            pass
        self.anomaly_var.set(
            ("⚠ " + "\n⚠ ".join(summary.anomalies)) if summary.anomalies else "")
        series = {}
        for key in filter(None, [summary.primary_key, "acc", "val_acc", "val_loss"]):
            values = summary.series(key)
            if values and key not in series:
                series[key] = values
        draw_line_chart(self.chart, series)

    def refresh_runs(self):
        self.runs_list.delete(0, "end")
        for record in self.app.runs.list(15):
            stamp = time.strftime("%d.%m %H:%M", time.localtime(record.started_at))
            self.runs_list.insert("end", f"{stamp}  {record.status_ru}  {record.command[:40]}")

    def send_log_to_mentor(self):
        tail = self.app.training.tail()
        if not tail.strip():
            messagebox.showinfo("Обучение", "Лог пуст — нечего отправлять.", parent=self)
            return
        prompt = (
            "Проанализируй лог обучения, найди ошибки и возможные причины проблем. "
            "Предложи конкретные исправления кода.\n\n```\n"
            + tail[-12000:]
            + "\n```"
        )
        self.app.show_page("chat")
        self.app.pages["chat"].send_preset(prompt)

    def send_progress_to_mentor(self):
        self.app.show_page("chat")
        self.app.pages["chat"].send_preset(
            "Проанализируй прогресс обучения. Что улучшается, что вызывает "
            "опасность, что стоит изменить?\n\n" + self.app.assessment_context()
        )

    def _tick(self):
        try:
            if self.winfo_exists():
                status = self.app.training.status()
                if status.running:
                    self.status_var.set(f"Выполняется: {status.command}")
                    self.refresh_log()
                else:
                    was_running = getattr(self, "_was_running", False)
                    self.status_var.set(
                        f"Не запущено. Последний код возврата: {status.returncode}"
                        if status.returncode is not None else "Обучение не запущено")
                    if was_running:
                        self._on_finished(status.returncode)
                self._was_running = status.running
        except Exception:  # noqa: BLE001 - the ticker must survive any UI hiccup
            pass
        self.after(1200, self._tick)

    def _on_finished(self, returncode):
        tail = self.app.training.tail()
        summary = parse_log(tail)
        if self._current_run_id:
            self.app.runs.finish(self._current_run_id, returncode,
                                 metrics_last=summary.last, best=summary.best,
                                 anomalies=summary.anomalies)
            self._current_run_id = None
        self.app.activity.log(
            "training",
            f"Обучение завершилось (код {returncode}); {metrics_brief(summary)}",
            returncode=returncode, anomalies=summary.anomalies,
        )
        self.refresh_log()
        self.refresh_runs()
        if returncode == 0:
            self.app.set_status("Обучение завершилось успешно")
            return
        self.app.set_status(f"Обучение завершилось с ошибкой (код {returncode})")
        if self.auto_analyze.get():
            self.app.show_page("chat")
            self.app.pages["chat"].send_preset(
                f"Обучение завершилось с кодом {returncode}. Проанализируй лог, "
                f"найди ошибку и предложи исправление.\n\n```\n{tail[-12000:]}\n```"
            )
