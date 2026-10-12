"""Chat page: conversational panel where the mentor works with the workspace."""
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
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.store = ChatStore()
        self.session = ChatSession()
        self._sessions_cache: list[ChatSession] = []
        self._busy = False
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        header = tk.Frame(self, bg=C["bg"])
        header.pack(fill="x", padx=22, pady=(18, 10))
        tk.Label(header, text="Чат с наставником", bg=C["bg"], fg=C["text"],
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(
            header,
            text="Диалог, инструменты и правки кода в выбранной рабочей папке. "
                 "Наставник читает файлы, ищет ошибки и предлагает изменения — "
                 "каждое изменение требует вашего подтверждения.",
            bg=C["bg"], fg=C["muted"], font=F_BASE, wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=22, pady=(0, 14))

        # Sessions column
        side = tk.Frame(body, bg=C["panel"], width=230)
        side.pack(side="left", fill="y", padx=(0, 12))
        side.pack_propagate(False)
        tk.Label(side, text="ДИАЛОГИ", bg=C["panel"], fg=C["muted"], font=F_SMALL,
                 anchor="w").pack(fill="x", padx=12, pady=(12, 6))
        self.sessions_list = tk.Listbox(side, bg=C["panel"], fg=C["text"],
                                        highlightthickness=0, bd=0,
                                        selectbackground=C["accent"],
                                        selectforeground="#ffffff",
                                        font=F_BASE, activestyle="none")
        self.sessions_list.pack(fill="both", expand=True, padx=8)
        self.sessions_list.bind("<<ListboxSelect>>", lambda _e: self._select_session())
        btns = tk.Frame(side, bg=C["panel"])
        btns.pack(fill="x", padx=8, pady=10)
        ttk.Button(btns, text="Новый", command=self.new_session).pack(side="left",
                                                                     fill="x", expand=True)
        ttk.Button(btns, text="Удалить", style="Danger.TButton",
                   command=self.delete_session).pack(side="left", fill="x", expand=True,
                                                     padx=(6, 0))

        # Chat column
        center = tk.Frame(body, bg=C["border"])
        center.pack(side="left", fill="both", expand=True)
        chat_inner = tk.Frame(center, bg=C["panel"])
        chat_inner.pack(fill="both", expand=True, padx=1, pady=1)

        self.messages = tk.Text(chat_inner, wrap="word", state="disabled", bd=0,
                                bg=C["panel"], fg=C["text"], font=F_BASE,
                                padx=16, pady=14, spacing3=6)
        self.messages.pack(fill="both", expand=True)
        self.messages.tag_configure("user", background=C["user_bubble"], lmargin1=60,
                                    lmargin2=60, rmargin=10, spacing1=2, spacing3=8)
        self.messages.tag_configure("assistant", background=C["assistant_bubble"],
                                    lmargin1=10, lmargin2=60, rmargin=60,
                                    relief="solid", borderwidth=0, spacing3=8)
        self.messages.tag_configure("tool", background=C["tool_bubble"], font=F_MONO,
                                    lmargin1=20, lmargin2=20, rmargin=20, spacing3=6)
        self.messages.tag_configure("meta", font=("Segoe UI", 8, "bold"), foreground=C["muted"])
        self.messages.tag_configure("sys", foreground=C["muted"], font=F_SMALL)

        input_bar = tk.Frame(chat_inner, bg=C["panel"])
        input_bar.pack(fill="x", padx=12, pady=(4, 12))
        self.input = tk.Text(input_bar, height=3, wrap="word", font=F_BASE, bd=1,
                             relief="solid", highlightthickness=0)
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Control-Return>", lambda _e: (self.send(), "break")[1])
        right = tk.Frame(input_bar, bg=C["panel"])
        right.pack(side="left", fill="y", padx=(10, 0))
        self.send_btn = ttk.Button(right, text="Отправить", style="Accent.TButton",
                                   command=self.send)
        self.send_btn.pack(fill="x")
        ttk.Button(right, text="Очистить", command=lambda: self.input.delete("1.0", "end")
                   ).pack(fill="x", pady=(6, 0))
        tk.Label(right, text="Ctrl+Enter", bg=C["panel"], fg=C["muted"], font=F_SMALL
                 ).pack(side="bottom")

        # Activity column
        side2 = tk.Frame(body, bg=C["panel"], width=280)
        side2.pack(side="left", fill="y", padx=(12, 0))
        side2.pack_propagate(False)
        tk.Label(side2, text="АКТИВНОСТЬ ИНСТРУМЕНТОВ", bg=C["panel"], fg=C["muted"],
                 font=F_SMALL, anchor="w").pack(fill="x", padx=12, pady=(12, 6))
        self.activity = tk.Text(side2, wrap="word", state="disabled", bd=0,
                                bg=C["panel_alt"] if "panel_alt" in C else C["panel"],
                                fg=C["muted"], font=F_MONO, padx=10, pady=8)
        self.activity.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.activity.tag_configure("ok", foreground=C["success"])
        self.activity.tag_configure("err", foreground=C["danger"])
        self.activity.tag_configure("act", foreground=C["accent"])
        self.hint_var = tk.StringVar(value="")
        tk.Label(side2, textvariable=self.hint_var, bg=C["panel"], fg=C["muted"],
                 font=F_SMALL, wraplength=250, justify="left").pack(fill="x", padx=12,
                                                                    pady=(0, 10))
        self._update_hint()
        self.refresh_sessions()
        self._render_messages()

    # -------------------------------------------------------------- sessions
    def _update_hint(self):
        root = self.app.workspace_root()
        if root:
            self.hint_var.set(f"Инструменты активны. Папка: {root}")
        else:
            self.hint_var.set("Рабочая папка не выбрана — инструменты отключены. "
                              "Выберите её на странице «Рабочая папка».")

    def on_show(self):
        self._update_hint()

    def refresh_sessions(self):
        self._sessions_cache = self.store.list_sessions()
        self.sessions_list.delete(0, "end")
        for session in self._sessions_cache:
            self.sessions_list.insert("end", session.title)

    def _select_session(self):
        selection = self.sessions_list.curselection()
        if not selection:
            return
        session = self._sessions_cache[selection[0]]
        if session.id == self.session.id:
            return
        if self._busy:
            messagebox.showinfo("Чат", "Дождитесь завершения текущего ответа.", parent=self)
            return
        self.session = session
        self._render_messages()

    def new_session(self):
        if self._busy:
            messagebox.showinfo("Чат", "Дождитесь завершения текущего ответа.", parent=self)
            return
        self.session = ChatSession()
        self.refresh_sessions()
        self._render_messages()
        self.set_activity("")

    def delete_session(self):
        selection = self.sessions_list.curselection()
        if not selection:
            return
        session = self._sessions_cache[selection[0]]
        if not messagebox.askyesno("Удалить диалог",
                                   f"Удалить «{session.title}»?", parent=self):
            return
        self.store.delete(session.id)
        if session.id == self.session.id:
            self.session = ChatSession()
        self.refresh_sessions()
        self._render_messages()

    # --------------------------------------------------------------- render
    def _render_messages(self):
        set_text(self.messages, "")
        self.messages.configure(state="normal")
        if not self.session.messages:
            self.messages.insert(
                "end",
                "Начните диалог: попросите наставника разобрать код, найти ошибку "
                "или объяснить метрики обучения.\n\nПримеры:\n"
                "• «Прочитай скрипт обучения и найди, почему растёт loss»\n"
                "• «Запусти тесты и почини падающий тест»\n"
                "• «Проанализируй лог и предложи исправления»\n",
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
                    args = fn.get("arguments", "")
                    self.messages.insert(
                        "end",
                        f"⚙ {fn.get('name', '?')} {args[:220]}\n",
                        "tool",
                    )
            elif message.role == "tool":
                preview = message.content.replace("\n", " ")[:220]
                self.messages.insert("end", f"→ {message.name}: {preview}\n", "tool")
        self.messages.configure(state="disabled")
        self.messages.see("end")

    def _insert_bubble(self, author: str, text: str, tag: str, created_at: float):
        stamp = time.strftime("%H:%M", time.localtime(created_at))
        self.messages.insert("end", f"{author} · {stamp}\n", "meta")
        self.messages.insert("end", text.rstrip() + "\n", tag)

    def set_activity(self, text: str):
        set_text(self.activity, text)

    def log_activity(self, text: str, tag: str | None = None):
        self.activity.configure(state="normal")
        self.activity.insert("end", text.rstrip() + "\n", tag or ())
        self.activity.configure(state="disabled")
        self.activity.see("end")

    def on_agent_event(self, kind: str, payload: dict):
        if kind == "tool_start":
            self.log_activity(f"→ {payload.get('description', payload.get('name', ''))}", "act")
        elif kind == "tool_result":
            mark = "ok" if payload.get("ok") else "err"
            self.log_activity(f"  [{mark}] {payload.get('summary', '')}", mark)
        elif kind == "assistant":
            count = payload.get("tool_calls", 0)
            if count:
                self.log_activity(f"наставник запрашивает инструментов: {count}")
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
            messagebox.showinfo("Чат", "Дождитесь завершения текущего ответа.", parent=self)
            return
        try:
            mentor = self.app.mentor_client()
        except MentorError as exc:
            messagebox.showerror("ИИ-наставник", str(exc), parent=self)
            self.app.show_page("settings")
            return

        root = self.app.workspace_root()
        workspace = WorkspaceTools(root) if root else None
        if root is None:
            self.log_activity("внимание: папка не выбрана, инструменты отключены", "err")

        self.session.add("user", text)
        self.store.save(self.session)
        self.refresh_sessions()
        self._render_messages()
        self.set_activity("")

        history = self.session.history_for_api()
        transcript: list[dict] = []
        settings = self.app.settings
        agent = MentorAgent(mentor, workspace, enable_tools=workspace is not None)

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
            self._render_messages()
            self.refresh_sessions()

        def failed(_error: str):
            # Keep whatever tool activity happened, but unlock the input.
            self._busy = False
            self.send_btn.configure(state="normal")
            for item in transcript:
                self.session.messages.append(ChatMessage.from_dict(item))
            self.store.save(self.session)
            self._render_messages()

        def work():
            return agent.run_turn(
                history,
                confirm=lambda name, args, desc: self.app.confirm_from_worker(
                    "Наставник хочет выполнить действие",
                    f"{desc}\n\nПодтвердить выполнение?",
                ),
                on_event=lambda kind, payload: self.app.post_event(
                    "chat_event", {"kind": kind, "payload": payload}),
                max_tokens=int(settings.mentor_max_tokens),
                temperature=float(settings.mentor_temperature),
                transcript=transcript,
            )

        self.app.start_async("Ответ наставника", work, done, failed)
