"""Bottom terminal panel: run commands in the workspace and see the output."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .tools import WorkspaceTools
from .ui_common import C, F_MONO, F_SMALL, set_text


class TerminalPanel(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["panel"])
        self.app = app
        self._history: list[str] = []
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=C["panel"])
        bar.pack(fill="x", padx=8, pady=(6, 4))
        tk.Label(bar, text="ТЕРМИНАЛ", bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left")
        self.cmd_entry = tk.Entry(bar, bd=1, relief="solid", font=F_MONO)
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.cmd_entry.bind("<Return>", lambda _e: self.run_command())
        self.cmd_entry.bind("<Up>", lambda _e: self._history_up())
        ttk.Button(bar, text="▶ Выполнить", style="Accent.TButton",
                   command=self.run_command).pack(side="left")
        ttk.Button(bar, text="Очистить",
                   command=lambda: set_text(self.output, "")).pack(side="left",
                                                                   padx=6)
        self.output = tk.Text(self, height=8, wrap="word", state="disabled",
                              bg=C["code_bg"], fg=C["code_fg"], font=F_MONO,
                              bd=0, padx=10, pady=6)
        self.output.pack(fill="both", expand=True, padx=1, pady=(0, 1))

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
        root = self.app.workspace_root()
        if not command:
            return
        if root is None:
            messagebox.showinfo("Терминал", "Сначала выберите рабочую папку.",
                                parent=self)
            return
        self._history.append(command)
        self.append(f"\n$ {command}\n")
        self.cmd_entry.delete(0, "end")
        workspace = WorkspaceTools(root)

        def done(result):
            stamp = time.strftime("%H:%M:%S")
            code = result.get("returncode", "?")
            self.append(result.get("output", "") + f"\n[код {code} · {stamp}]\n")

        self.app.start_async(
            f"Выполнение: {command}",
            lambda: workspace.run_command(command, timeout_seconds=120),
            done,
        )
