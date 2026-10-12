"""Training page: run training in the workspace, watch logs, involve the mentor."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .training import TrainingError
from .ui_common import C, F_BASE, F_MONO, F_SMALL, card, page_header, set_text


class TrainingPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._build()
        self._tick()

    def _build(self):
        header = page_header(
            self,
            "Обучение",
            "Запуск команды обучения в рабочей папке, живой лог и разбор ошибок "
            "наставником. Наставник может прочитать код, найти причину и предложить "
            "исправление — после вашего подтверждения.",
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        run_card = card(self, "Команда обучения")
        run_card.pack(fill="x", padx=24, pady=(0, 12))
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

        log_card = card(self, "Лог")
        log_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        bar = tk.Frame(log_card, bg=C["panel"])
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Обновить лог", command=self.refresh_log).pack(side="left")
        ttk.Button(bar, text="Отправить лог наставнику",
                   command=self.send_log_to_mentor).pack(side="left", padx=8)
        ttk.Button(bar, text="Открыть чат",
                   command=lambda: self.app.show_page("chat")).pack(side="left")

        self.log_text = tk.Text(log_card, wrap="word", state="disabled",
                                bg=C["code_bg"], fg=C["code_fg"], font=F_MONO,
                                bd=0, padx=12, pady=10)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("err", foreground="#f87171")
        self.log_text.tag_configure("ok", foreground="#4ade80")

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
            self.app.training.start(command, root)
        except TrainingError as exc:
            messagebox.showerror("Обучение", str(exc), parent=self)
            return
        self.app.set_status("Обучение запущено")
        self.refresh_log()

    def stop_training(self):
        try:
            self.app.training.stop()
        except TrainingError as exc:
            messagebox.showinfo("Обучение", str(exc), parent=self)
            return
        self.app.set_status("Отправлен сигнал остановки")

    def refresh_log(self):
        set_text(self.log_text, self.app.training.tail() or "Лог пуст.")

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
        chat = self.app.pages["chat"]
        chat.send_preset(prompt)

    def _tick(self):
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
        self.after(1200, self._tick)

    def _on_finished(self, returncode):
        self.refresh_log()
        if returncode == 0:
            self.app.set_status("Обучение завершилось успешно")
            return
        self.app.set_status(f"Обучение завершилось с ошибкой (код {returncode})")
        if self.auto_analyze.get():
            tail = self.app.training.tail()
            self.app.show_page("chat")
            chat = self.app.pages["chat"]
            chat.send_preset(
                f"Обучение завершилось с кодом {returncode}. Проанализируй лог, "
                f"найди ошибку и предложи исправление.\n\n```\n{tail[-12000:]}\n```"
            )
