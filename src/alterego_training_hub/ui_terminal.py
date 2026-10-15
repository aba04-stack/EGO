"""Bottom terminal panel: run commands locally or on a connected server."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .i18n import t
from .tools import WorkspaceTools
from .ui_common import F_MONO, F_SMALL, C

LOCAL_TARGET = t(t('Локально'))


class TerminalPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["panel"])
        self.app = app
        self._history: list[str] = []
        self._open = True
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=C["panel"])
        bar.pack(fill="x", padx=8, pady=(6, 4))
        self.arrow = tk.Label(bar, text="▼", bg=C["panel"], fg=C["muted"],
                              font=F_SMALL, cursor="hand2")
        self.arrow.pack(side="left")
        title = tk.Label(bar, text=t(t('ввод команды')), bg=C["panel"], fg=C["muted"],
                         font=F_SMALL, cursor="hand2")
        title.pack(side="left", padx=(2, 10))
        for widget in (self.arrow, title):
            widget.bind("<Button-1>", lambda _e: self.toggle())

        tk.Label(bar, text=t(t('Цель')), bg=C["panel"], fg=C["muted"], font=F_SMALL).pack(
            side="left", padx=(0, 4))
        self.target = ttk.Combobox(bar, width=16, state="readonly",
                                   values=(LOCAL_TARGET,))
        self.target.set(LOCAL_TARGET)
        self.target.pack(side="left", padx=(0, 8))

        self.body = tk.Frame(self, bg=C["panel"])
        self.body.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        cmd_row = tk.Frame(self.body, bg=C["panel"])
        cmd_row.pack(fill="x", padx=8, pady=(0, 4))
        self.cmd_entry = tk.Entry(cmd_row, bd=1, relief="solid", font=F_MONO)
        self.cmd_entry.pack(side="left", fill="x", expand=True)
        self.cmd_entry.bind("<Return>", lambda _e: self.run_command())
        self.cmd_entry.bind("<Up>", lambda _e: self._history_up())
        ttk.Button(cmd_row, text=t(t('▶ Выполнить')), style="Accent.TButton",
                   command=self.run_command).pack(side="left", padx=(8, 0))
        self.output = tk.Text(self.body, height=6, wrap="word", state="disabled",
                              bg=C["code_bg"], fg=C["code_fg"], font=F_MONO,
                              bd=0, padx=10, pady=6)
        self.output.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    def toggle(self):
        self.set_open(not self._open)

    def set_open(self, open_: bool):
        open_ = bool(open_)
        if open_ == self._open:
            return
        self._open = open_
        self.arrow.configure(text="▼" if open_ else "▶")
        if open_:
            self.body.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        else:
            self.body.pack_forget()

    @property
    def is_open(self) -> bool:
        return self._open

    def refresh_targets(self):
        names = [LOCAL_TARGET]
        try:
            names += [entry.name for entry in self.app.server_manager().list()]
        except Exception:
            pass
        current = self.target.get() or LOCAL_TARGET
        self.target.configure(values=names)
        self.target.set(current if current in names else LOCAL_TARGET)

    def _history_up(self):
        if self._history:
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.insert(0, self._history[-1])

    def append(self, text: str):
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.configure(state="disabled")
        self.output.see("end")

    def run_command(self):
        command = self.cmd_entry.get().strip()
        if not command:
            return
        self._history.append(command)
        target = self.target.get() or LOCAL_TARGET
        self.append(f"\n[{target}] $ {command}\n")
        self.cmd_entry.delete(0, "end")

        if target != LOCAL_TARGET:
            def done(result):
                stamp = time.strftime("%H:%M:%S")
                code = result.get("exit_code", "?")
                self.append(result.get("output", "") + t(t('\n[код {code} · {stamp}]\n')).format(code=code, stamp=stamp))

            self.app.start_async(
                t(t('Команда на {target}')).format(target=target),
                lambda: self.app.server_manager().run_command(target, command),
                done,
            )
            return

        root = self.app.workspace_root()
        if root is None:
            messagebox.showinfo(t(t('Терминал')), t(t('Сначала выберите рабочую папку.')),
                                parent=self)
            return
        workspace = WorkspaceTools(root)

        def done_local(result):
            stamp = time.strftime("%H:%M:%S")
            code = result.get("returncode", "?")
            self.append(result.get("output", "") + t(t('\n[код {code} · {stamp}]\n')).format(code=code, stamp=stamp))

        self.app.start_async(
            t(t('Выполнение: {command}')).format(command=command),
            lambda: workspace.run_command(command, timeout_seconds=120),
            done_local,
        )
