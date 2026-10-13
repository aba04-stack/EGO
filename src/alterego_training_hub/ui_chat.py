"""Right-side chat panel: mentor assistant or autonomous agent with tools."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .agent import MentorAgent
from .chat import ChatMessage, ChatSession, ChatStore
from .mentor import MentorError
from .tools import WorkspaceTools
from .ui_common import C, F_BASE, F_MONO, F_SMALL, set_text


class ChatPage(tk.Frame):
    """Docked chat panel (right side of the IDE layout)."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=C["panel"])
        self.app = app
        self.store = ChatStore()
        self.session = ChatSession()
        self._sessions_cache: list[ChatSession] = []
        self._busy = False
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = tk.Frame(self, bg=C["panel"])
        top.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(top, text="Наставник", bg=C["panel"], fg=C["text"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        row = tk.Frame(top, bg=C["panel"])
        row.pack(fill="x", pady=(6, 0))
        self.sessions_combo = ttk.Combobox(row, state="readonly", width=22)
        self.sessions_combo.pack(side="left")
        self.sessions_combo.bind("<<ComboboxSelected>>", lambda _e: self._select_session())
        ttk.Button(row, text="+", width=3,
                   command=self.new_session).pack(side="left", padx=(4, 0))
        ttk.Button(row, text="✕", width=3, style="Danger.TButton",
                   command=self.delete_session).pack(side="left", padx=(3, 0))

        mode_row = tk.Frame(top, bg=C["panel"])
        mode_row.pack(fill="x", pady=(6, 0))
        tk.Label(mode_row, text="Режим", bg=C["panel"], fg=C["muted"],
                 font=F_SMALL).pack(side="left", padx=(0, 6))
        self.autonomy_var = tk.StringVar(value=self.app.settings.chat_autonomy)
        self.mode_btn = tk.Label(
            mode_row, text="", bg=C["accent"], fg="#ffffff", font=F_SMALL,
            padx=10, pady=4, cursor="hand2",
        )
        self.mode_btn.pack(side="left")
        self.mode_btn.bind("<Button-1>", lambda _e: self.toggle_mode())
        self._render_mode()
        self.status_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.status_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL, wraplength=340, justify="left").pack(anchor="w",
                                                                    pady=(6, 0))

        self.messages = tk.Text(self, wrap="word", state="disabled", bd=0,
                                bg=C["panel"], fg=C["text"], font=F_BASE,
                                padx=10, pady=8, spacing3=5)
        self.messages.pack(fill="both", expand=True)
        self.messages.tag_configure("user", background=C["user_bubble"], lmargin1=40,
                                    lmargin2=40, rmargin=6, spacing3=6)
        self.messages.tag_configure("assistant", background=C["assistant_bubble"],
                                    lmargin1=6, lmargin2=40, rmargin=20, spacing3=6)
        self.messages.tag_configure("tool", background=C["tool_bubble"], font=F_MONO,
                                    lmargin1=12, lmargin2=12, rmargin=12)
        self.messages.tag_configure("meta", font=("Segoe UI", 8, "bold"),
                                    foreground=C["muted"])
        self.messages.tag_configure("h", font=("Segoe UI", 10, "bold"))
        self.messages.tag_configure("sys", foreground=C["muted"], font=F_SMALL)
        self.messages.tag_configure("act", foreground=C["accent"])
        self.messages.tag_configure("err", foreground=C["danger"])

        quick = tk.Frame(self, bg=C["panel"])
        quick.pack(fill="x", padx=8, pady=(4, 0))
        for label, builder in [
            ("Оценка", lambda: self.app.assessment_prompt()),
            ("Прогресс", lambda: (
                "Проанализируй прогресс обучения и предложи улучшения.\n\n"
                + self.app.assessment_context())),
            ("Ошибки", lambda: (
                "Найди ошибки в логе обучения и предложи исправления.\n\n```\n"
                + self.app.training.tail(8000) + "\n```")),
        ]:
            ttk.Button(quick, text=label, width=8,
                       command=lambda b=builder: self.send_preset(b())
            ).pack(side="left", padx=(0, 4))

        input_bar = tk.Frame(self, bg=C["panel"])
        input_bar.pack(fill="x", padx=8, pady=(6, 10))
        self.input = tk.Text(input_bar, height=3, wrap="word", font=F_BASE, bd=1,
                             relief="solid", highlightthickness=0)
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Control-Return>", lambda _e: (self.send(), "break")[1])
        self.send_btn = ttk.Button(input_bar, text="➤", width=4,
                                   style="Accent.TButton", command=self.send)
        self.send_btn.pack(side="left", fill="y", padx=(6, 0))

        self._update_hint()
        self.refresh_sessions()
        self._render_messages()

    def _render_mode(self):
        if self.autonomy_var.get() == "agent":
            self.mode_btn.configure(text="● Режим агента — действует свободно",
                                    bg=C["success"])
        else:
            self.mode_btn.configure(text="○ Ассистент — подтверждает действия",
                                    bg=C["accent"])

    def toggle_mode(self):
        new = "assist" if self.autonomy_var.get() == "agent" else "agent"
        self.autonomy_var.set(new)
        self.app.settings.chat_autonomy = new
        self.app.save_settings()
        self._render_mode()

    # -------------------------------------------------------------- sessions
    def _update_hint(self):
        root = self.app.workspace_root()
        mode = "агент" if self.autonomy_var.get() == "agent" else "ассистент"
        if root:
            self.status_var.set(f"{mode} · папка: {root.name}")
        else:
            self.status_var.set(f"{mode} · рабочая папка не выбрана — инструменты файлов отключены")

    def focus_input(self):
        try:
            self.input.focus_set()
        except Exception:  # noqa: BLE001 - widget may be gone during shutdown
            pass

    def on_show(self):
        self._update_hint()

    def refresh_sessions(self):
        self._sessions_cache = self.store.list_sessions()
        labels = [session.title for session in self._sessions_cache] or ["Новый диалог"]
        self.sessions_combo.configure(values=labels)
        if not self.sessions_combo.get():
            self.sessions_combo.set(labels[0])

    def _select_session(self):
        title = self.sessions_combo.get()
        for session in self._sessions_cache:
            if session.title == title and session.id != self.session.id:
                if self._busy:
                    messagebox.showinfo("Чат", "Дождитесь завершения ответа.",
                                        parent=self)
                    return
                self.session = session
                self._render_messages()
                return

    def new_session(self):
        if self._busy:
            messagebox.showinfo("Чат", "Дождитесь завершения ответа.", parent=self)
            return
        self.session = ChatSession()
        self.refresh_sessions()
        self.sessions_combo.set("Новый диалог")
        self._render_messages()

    def delete_session(self):
        if self._busy:
            return
        if self.session.id and self.session.messages:
            if not messagebox.askyesno("Удалить диалог",
                                       f"Удалить «{self.session.title}»?", parent=self):
                return
            self.store.delete(self.session.id)
        self.session = ChatSession()
        self.refresh_sessions()
        self.sessions_combo.set("Новый диалог")
        self._render_messages()

    # --------------------------------------------------------------- render
    def _render_messages(self):
        set_text(self.messages, "")
        self.messages.configure(state="normal")
        if not self.session.messages:
            self.messages.insert(
                "end",
                "Диалог пуст. Попросите наставника разобрать код, найти ошибку "
                "или запустите режим агента и дайте цель.\n\n"
                "Пример цели для агента:\n"
                "«Запусти тесты, найди падающий, почини и проверь снова.»\n",
                "sys",
            )
        for message in self.session.messages:
            if message.role == "user":
                self._insert_bubble("Вы", message.content, "user", message.created_at)
            elif message.role == "assistant":
                if message.content:
                    self._insert_bubble("Наставник", message.content, "assistant",
                                        message.created_at)
                for call in message.tool_calls:
                    fn = call.get("function", {})
                    self.messages.insert("end",
                                         f"⚙ {fn.get('name', '?')} "
                                         f"{str(fn.get('arguments', ''))[:160]}\n",
                                         "tool")
            elif message.role == "tool":
                preview = message.content.replace("\n", " ")[:160]
                self.messages.insert("end", f"→ {message.name}: {preview}\n", "tool")
        self.messages.configure(state="disabled")
        self.messages.see("end")

    def _insert_bubble(self, author: str, text: str, tag: str, created_at: float):
        stamp = time.strftime("%H:%M", time.localtime(created_at))
        self.messages.insert("end", f"{author} · {stamp}\n", "meta")
        for line in text.rstrip().splitlines():
            heading = line.lstrip().startswith(("#", "**")) and tag == "assistant"
            self.messages.insert("end", line + "\n", (tag, "h") if heading else tag)

    def log_activity(self, text: str, tag: str | None = None):
        self.messages.configure(state="normal")
        self.messages.insert("end", text.rstrip() + "\n", tag or ())
        self.messages.configure(state="disabled")
        self.messages.see("end")

    def on_agent_event(self, kind: str, payload: dict):
        if kind == "tool_start":
            self.log_activity(f"→ {payload.get('description', payload.get('name', ''))}",
                              "act")
        elif kind == "tool_result":
            mark = "ok" if payload.get("ok") else "err"
            self.log_activity(f"  [{mark}] {payload.get('summary', '')}", mark)
            self.app.activity.log(
                "mentor_tool",
                f"{payload.get('name', '?')}: {payload.get('summary', '')[:120]}",
                ok=bool(payload.get("ok")),
            )
        elif kind == "assistant":
            count = payload.get("tool_calls", 0)
            if count:
                self.log_activity(f"инструментов к вызову: {count}")
            elif payload.get("text"):
                self.log_activity("наставник формирует ответ")

    # ----------------------------------------------------------------- send
    def send(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self.send_preset(text)

    def send_preset(self, text: str):
        if self._busy:
            messagebox.showinfo("Чат", "Дождитесь завершения ответа.", parent=self)
            return
        try:
            mentor = self.app.mentor_client()
        except MentorError as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)
            self.app.show_page("settings")
            return

        root = self.app.workspace_root()
        workspace = None
        if root is not None:
            try:
                workspace = WorkspaceTools(root, backup_dir=self.app.backup_dir())
            except Exception as exc:
                self.log_activity(f"ошибка рабочей папки: {exc}", "err")

        self.session.add("user", text)
        self.store.save(self.session)
        self.refresh_sessions()
        self._render_messages()

        history = self.session.history_for_api()
        transcript: list[dict] = []
        settings = self.app.settings
        extra_tools, extra_schemas, extra_mutations = self.app.agent_extra_tools()
        autonomy = self.autonomy_var.get()
        agent = MentorAgent(
            mentor, workspace,
            enable_tools=workspace is not None or bool(extra_tools),
            extra_tools=extra_tools,
            extra_schemas=extra_schemas,
            extra_mutations=extra_mutations,
            autonomy=autonomy,
            max_steps=14 if autonomy == "agent" else 8,
        )

        self._busy = True
        self.send_btn.configure(state="disabled")

        def done(value):
            self._busy = False
            self.send_btn.configure(state="normal")
            reply = value
            for item in transcript:
                self.session.messages.append(ChatMessage.from_dict(item))
            self.session.add("assistant", reply.text)
            self.store.save(self.session)
            self._maybe_save_report(reply.text)
            self._render_messages()
            self.refresh_sessions()

        def failed(_error: str):
            self._busy = False
            self.send_btn.configure(state="normal")
            for item in transcript:
                self.session.messages.append(ChatMessage.from_dict(item))
            self.store.save(self.session)
            self._render_messages()

        def work():
            common = dict(
                confirm=None if autonomy == "agent" else (
                    lambda name, args, desc: self.app.confirm_from_worker(
                        "Действие наставника", f"{desc}\n\nПодтвердить выполнение?")),
                on_event=lambda kind, payload: self.app.post_event(
                    "chat_event", {"kind": kind, "payload": payload}),
                max_tokens=int(settings.mentor_max_tokens),
                temperature=float(settings.mentor_temperature),
                transcript=transcript,
            )
            if autonomy == "agent":
                return agent.run_goal(text, **common)
            return agent.run_turn(history, **common)

        self.app.start_async("Ответ наставника", work, done, failed)

    def _maybe_save_report(self, text: str):
        from .report import parse_report

        report = parse_report(text)
        if report.is_empty():
            return
        structured = (report.score is not None or report.strengths
                      or report.weaknesses or report.recommendations)
        if not structured:
            return
        self.app.reports.save(report)
        self.app.activity.log(
            "report",
            "Сохранена оценка наставника"
            + (f" ({report.score:g}/10)" if report.score is not None else ""),
        )
        self.log_activity("оценка сохранена в «Модель и прогресс»", "ok")
