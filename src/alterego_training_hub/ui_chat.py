"""Right-side chat panel: mentor assistant or autonomous agent with tools."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .agent import MentorAgent
from .chat import ChatMessage, ChatSession, ChatStore
from .i18n import t
from .mentor import MentorError
from .tools import WorkspaceTools
from .ui_common import F_BASE, F_MONO, F_SMALL, C, set_text


class ChatPage(tk.Frame):
    """Docked chat panel (right side of the IDE layout)."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=C["panel"])
        self.app = app
        self.store = ChatStore()
        self.session = ChatSession()
        self._sessions_cache: list[ChatSession] = []
        self._busy = False
        self._cancel_event: threading.Event | None = None
        self._last_usage: dict = {}
        self._last_model: str = ""
        self._last_question: str = ""
        self._last_answer: str = ""
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = tk.Frame(self, bg=C["panel"])
        top.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(top, text=t(t('Наставник')), bg=C["panel"], fg=C["text"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        row = tk.Frame(top, bg=C["panel"])
        row.pack(fill="x", pady=(6, 0))
        self.sessions_combo = ttk.Combobox(row, state="readonly", width=15)
        self.sessions_combo.pack(side="left", fill="x", expand=True)
        self.sessions_combo.bind("<<ComboboxSelected>>", lambda _e: self._select_session())
        self.new_session_btn = ttk.Button(
            row, text="+", width=3, command=self.new_session,
        )
        self.new_session_btn.pack(side="left", padx=(4, 0))
        self.delete_session_btn = ttk.Button(
            row, text="✕", width=3, style="Danger.TButton",
            command=self.delete_session,
        )
        self.delete_session_btn.pack(side="left", padx=(3, 0))

        # All session actions use equal columns within the dock width.
        extras = tk.Frame(top, bg=C["panel"])
        extras.pack(fill="x", pady=(6, 0))
        self.session_action_buttons = []
        for column, (label, command) in enumerate((
            (t(t("Выгрузить")), self.export_session),
            (t(t("Импорт")), self.import_session),
            (t(t("Метрики")), self.post_dashboard),
        )):
            button = ttk.Button(extras, text=label, command=command, width=10)
            button.grid(
                row=0, column=column, sticky="ew",
                padx=(0 if column == 0 else 4, 0),
            )
            extras.columnconfigure(column, weight=1, uniform="session-actions")
            self.session_action_buttons.append(button)

        search_row = tk.Frame(top, bg=C["panel"])
        search_row.pack(fill="x", pady=(6, 0))
        self.session_search_var = tk.StringVar(value="")
        _search = tk.Entry(search_row, textvariable=self.session_search_var,
                           bd=1, relief="solid", font=F_SMALL)
        _search.pack(fill="x")
        _search.bind("<KeyRelease>", lambda _e: self.apply_session_filter())

        mode_row = tk.Frame(top, bg=C["panel"])
        mode_row.pack(fill="x", pady=(6, 0))
        tk.Label(mode_row, text=t(t('Режим')), bg=C["panel"], fg=C["muted"],
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
                                bg=C["panel_alt"], fg=C["text"], font=F_BASE,
                                padx=12, pady=10, spacing3=6)
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

        # Live plan checklist published by the agent via update_plan.
        self.tasks_var = tk.StringVar(value="")
        self.tasks_label = tk.Label(
            self, textvariable=self.tasks_var, bg=C["panel"], fg=C["muted"],
            font=F_SMALL, wraplength=340, justify="left", anchor="w")
        self.tasks_label.pack(fill="x", padx=8, pady=(2, 0))
        for label, builder in [
            (t(t('Оценка')), lambda: self.app.assessment_prompt()),
            (t(t('Прогресс')), lambda: (
                t(t('Проанализируй прогресс обучения и предложи улучшения.\n\n'))
                + self.app.assessment_context())),
            (t(t('Ошибки')), lambda: (
                t(t('Найди ошибки в логе обучения и предложи исправления.\n\n```\n'))
                + self.app.training.tail(8000) + "\n```")),
        ]:
            ttk.Button(quick, text=label, width=8,
                       command=lambda b=builder: self.send_preset(b())
            ).pack(side="left", padx=(0, 4))

        input_bar = tk.Frame(self, bg=C["panel"])
        input_bar.pack(fill="x", padx=8, pady=(6, 10))
        self.attach_btn = ttk.Button(input_bar, text="📎", width=3,
                                     command=self.attach_file)
        self.attach_btn.pack(side="left", fill="y", padx=(0, 6))
        from .ui_common import attach_tooltip

        attach_tooltip(self.attach_btn,
                       t(t('Прикрепить файл к сообщению')))
        self.input = tk.Text(input_bar, height=3, wrap="word", font=F_BASE, bd=1,
                             relief="solid", highlightthickness=0)
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Control-Return>", lambda _e: (self.send(), "break")[1])
        self.send_btn = ttk.Button(input_bar, text="➤", width=4,
                                   style="Accent.TButton", command=self.send)
        self.send_btn.pack(side="left", fill="y", padx=(6, 0))
        self.stop_btn = ttk.Button(input_bar, text="⏹", width=4,
                                   style="Danger.TButton",
                                   command=self.stop_agent, state="disabled")
        self.stop_btn.pack(side="left", fill="y", padx=(6, 0))
        attach_tooltip(self.stop_btn, t(t('Остановить агента')))
        self.resume_btn = ttk.Button(input_bar, text="▶", width=4,
                                     command=self.resume_agent,
                                     state="disabled")
        self.resume_btn.pack(side="left", fill="y", padx=(6, 0))
        attach_tooltip(self.resume_btn, t(t('Продолжить после остановки')))

        self.composer_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.composer_var, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL, anchor="e").pack(
                     fill="x", padx=10, pady=(0, 6))
        self.input.bind("<KeyRelease>", lambda _e: self._update_composer())

        self._update_hint()
        self.refresh_sessions()
        self._render_messages()

    def _update_composer(self):
        from .context_view import estimate_tokens

        try:
            text = self.input.get("1.0", "end").strip()
        except Exception:
            text = ""
        self.composer_var.set(
            t(t('≈ {v1} ток. · Ctrl+Enter — отправить')).format(
                v1=estimate_tokens(text)) if text else "")

    def _render_mode(self):
        if self.autonomy_var.get() == "agent":
            self.mode_btn.configure(text=t(t('● Режим агента — действует свободно')),
                                    bg=C["success"])
        else:
            self.mode_btn.configure(text=t(t('○ Ассистент — подтверждает действия')),
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
        mode = t(t('агент')) if self.autonomy_var.get() == "agent" else t(t('ассистент'))
        if root:
            self.status_var.set(t(t('{mode} · папка: {v2}')).format(mode=mode, v2=root.name))
        else:
            self.status_var.set(t(t('{mode} · рабочая папка не выбрана — инструменты файлов отключены')).format(mode=mode))

    def focus_input(self):
        try:
            self.input.focus_set()
        except Exception:
            pass

    def on_show(self):
        self._update_hint()

    def refresh_sessions(self):
        self._sessions_cache = self.store.list_sessions()
        labels = self.filtered_session_titles()
        self.sessions_combo.configure(values=labels)
        if not self.sessions_combo.get():
            self.sessions_combo.set(labels[0])

    def filtered_session_titles(self) -> list[str]:
        from .ui_patterns import filter_titles

        query = ""
        var = getattr(self, "session_search_var", None)
        if var is not None:
            try:
                query = var.get()
            except Exception:
                query = ""
        titles = [session.title for session in self._sessions_cache]
        return filter_titles(titles, query) or [t(t('Новый диалог'))]

    def apply_session_filter(self):
        labels = self.filtered_session_titles()
        self.sessions_combo.configure(values=labels)
        if labels:
            self.sessions_combo.set(labels[0])

    def _select_session(self):
        title = self.sessions_combo.get()
        for session in self._sessions_cache:
            if session.title == title and session.id != self.session.id:
                if self._busy:
                    messagebox.showinfo(t(t('Чат')), t(t('Дождитесь завершения ответа.')),
                                        parent=self)
                    return
                self.session = session
                self._render_messages()
                return

    def new_session(self):
        if self._busy:
            messagebox.showinfo(t(t('Чат')), t(t('Дождитесь завершения ответа.')), parent=self)
            return
        self.session = ChatSession()
        self.refresh_sessions()
        self.sessions_combo.set(t(t('Новый диалог')))
        self._render_messages()

    def delete_session(self):
        if self._busy:
            return
        if self.session.id and self.session.messages:
            if not messagebox.askyesno(t(t('Удалить диалог')),
                                       t(t('Удалить «{v1}»?')).format(v1=self.session.title), parent=self):
                return
            self.store.delete(self.session.id)
        self.session = ChatSession()
        self.refresh_sessions()
        self.sessions_combo.set(t(t('Новый диалог')))
        self._render_messages()

    def export_session(self):
        from tkinter import filedialog

        from .session_share import export_session as _export

        if not self.session.messages:
            messagebox.showinfo(t(t('Сессия')), t(t('Диалог пуст — нечего выгружать.')),
                                parent=self)
            return
        path = filedialog.asksaveasfilename(
            title=t(t('Выгрузить сессию')), defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("HTML", "*.html"),
                       ("JSON", "*.json")])
        if not path:
            return
        fmt = path.rsplit(".", 1)[-1].lower()
        try:
            exported = _export(self.session, path, fmt=fmt)
        except Exception as exc:
            messagebox.showerror(t(t('Сессия')), str(exc), parent=self)
            return
        self.app.activity.log("share",
                              t(t('Сессия выгружена: {v1} ({v3} сообщений)')).format(v1=exported.path, v3=exported.messages))
        messagebox.showinfo(t(t('Сессия')),
                            t(t('Готово: {v1} сообщений → {v3}')).format(v1=exported.messages, v3=exported.path), parent=self)

    def import_session(self):
        from tkinter import filedialog

        from .session_share import import_session as _import

        path = filedialog.askopenfilename(
            title=t(t('Импорт сессии')), filetypes=[(t(t('JSON сессии')), "*.json"),
                                              (t(t('Все файлы')), "*.*")])
        if not path:
            return
        try:
            session = _import(path)
        except Exception as exc:
            messagebox.showerror(t(t('Сессия')), str(exc), parent=self)
            return
        self.session = session
        self.store.save(session)
        self.refresh_sessions()
        self.sessions_combo.set(session.title)
        self._render_messages()
        self.app.activity.log("share",
                              t(t('Сессия импортирована: {v1}')).format(v1=session.title))

    def post_dashboard(self):
        """Post a compact metrics dashboard into the conversation."""
        from .dashboard import build_dashboard
        from .metrics import parse_log

        summary = parse_log(self.app.training.tail())
        text = build_dashboard(summary, title=t(t('Прогресс обучения')))
        self.session.add("assistant", text)
        self._render_messages()

    # ------------------------------------------------- прозрачность (этап 26)
    def last_thought_text(self) -> str:
        """Protocol («Мысль → Действие → Ответ») of the last assistant reply."""
        from .thought_stream import parse_thought_block, render_thoughts_or_hint

        for message in reversed(self.session.messages):
            if message.role == "assistant" and message.content:
                record = parse_thought_block(message.content)
                return render_thoughts_or_hint(
                    record,
                    hint=t(t('Модель не использовала структурный протокол в последнем ответе. Включите «Протокол мыслей» на странице «Модель» — тогда каждый ответ будет раскрываться в цепочку «Мысль → Действие → Ответ».')))
        return t(t('Пока нет ответов наставника.'))

    def show_thoughts(self):
        messagebox.showinfo(t(t('Мысли агента')), self.last_thought_text(),
                            parent=self)

    def action_entries(self):
        from .action_trace import action_entries_from_messages

        return action_entries_from_messages(self.session.messages)

    def actions_text(self) -> str:
        entries = self.action_entries()
        if not entries:
            return t(t('Агент пока не вызывал инструментов в этом диалоге.'))
        return "\n".join(entry.line() for entry in entries[-20:])

    def show_actions(self):
        messagebox.showinfo(t(t('Что агент сделал')), self.actions_text(),
                            parent=self)

    def explain_last_action(self):
        """Ask the agent to explain its most recent tool call."""
        from .action_trace import explain_prompt

        entries = self.action_entries()
        if not entries:
            messagebox.showinfo(t(t('Действия')), self.actions_text(), parent=self)
            return
        self.send_preset(explain_prompt(entries[-1]))

    def context_text(self) -> str:
        from .agent import DEFAULT_AGENT_SYSTEM_PROMPT
        from .context_view import build_context_view

        system_extra = str(getattr(self.app.settings, "agent_system_extra", "") or "")
        system = DEFAULT_AGENT_SYSTEM_PROMPT
        if system_extra:
            system += "\n\nAdditional user instructions:\n" + system_extra[:2000]
        view = build_context_view(
            system_prompt=system,
            messages=self.session.history_for_api(),
            model=self._last_model or self.app.settings.mentor_model,
            last_usage=self._last_usage)
        return view.render()

    def show_context(self):
        messagebox.showinfo(t(t('Контекст модели')), self.context_text(),
                            parent=self)

    def run_critique_last(self):
        """Second read-only pass: check the last answer against evidence."""
        from .critique import run_critic

        answer = self._last_answer
        if not answer:
            for message in reversed(self.session.messages):
                if message.role == "assistant" and message.content:
                    answer = message.content
                    break
        if not answer:
            messagebox.showinfo(t(t('Критик')), t(t('Пока нет ответов для проверки.')),
                                parent=self)
            return
        try:
            mentor = self.app.mentor_client()
        except MentorError as exc:
            messagebox.showerror(t(t('Критик')), str(exc), parent=self)
            return
        evidence = self.actions_text()
        if "не вызывал" in evidence:
            evidence = ""

        def work():
            return run_critic(mentor, question=self._last_question,
                              answer=answer, evidence=evidence)

        def done(report):
            self.session.add("assistant", "🔍 " + t(t('Критик')) + ": "
                             + report.flag() + "\n" + report.render())
            self.store.save(self.session)
            self._render_messages()

        self.app.start_async(t(t('Проверка ответа')), work, done)

    # --------------------------------------------------------------- render
    def _render_messages(self):
        set_text(self.messages, "")
        self.messages.configure(state="normal")
        if not self.session.messages:
            self.messages.insert(
                "end",
                t(t('Диалог пуст. Попросите наставника разобрать код, найти ошибку или запустите режим агента и дайте цель.\n\nПример цели для агента:\n«Запусти тесты, найди падающий, почини и проверь снова.»\n')),
                "sys",
            )
        for message in self.session.messages:
            if message.role == "user":
                self._insert_bubble(t(t('Вы')), message.content, "user", message.created_at)
            elif message.role == "assistant":
                if message.content:
                    from .thought_stream import parse_thought_block

                    record = parse_thought_block(message.content)
                    if record.has_protocol:
                        for step in record.steps:
                            self.messages.insert("end", step.line() + "\n", "sys")
                    self._insert_bubble(
                        t(t('Наставник')),
                        record.answer if record.has_protocol else message.content,
                        "assistant", message.created_at)
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
        if kind == "retry":
            self.log_activity(
                t(t('↻ повтор запроса к модели (попытка {v1})')).format(
                    v1=payload.get("attempt", "?")), "err")
            return
        if kind == "cancelled":
            self.log_activity("⏹ " + t(t('Агент остановлен пользователем')), "err")
            return
        if kind == "parallel_batch":
            self.log_activity(
                t(t('⚡ параллельно: {v1} чтений')).format(
                    v1=payload.get("count", "?")), "act")
            return
        if kind == "loop_detected":
            self.log_activity(
                "⚠ " + t(t('Защита от зацикливания: агент остановлен')), "err")
            return
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
                self.log_activity(t(t('инструментов к вызову: {count}')).format(count=count))
            elif payload.get("text"):
                self.log_activity(t(t('наставник формирует ответ')))
        elif kind == "plan":
            tasks = payload.get("tasks") or []
            marks = {"done": "✓", "failed": "✗", "in_progress": "▶", "pending": "○"}
            self.tasks_var.set("   ".join(
                f"{marks.get(task.get('status', 'pending'), '○')} "
                f"{str(task.get('title', ''))[:40]}"
                for task in tasks[:6]))
            done = sum(1 for task in tasks if task.get("status") == "done")
            self.log_activity(t(t('план обновлён: {done}/{v3} шагов готово')).format(done=done, v3=len(tasks)))

    def resume_agent(self):
        """Resume a stopped turn from the transcript (этап 38)."""
        if self._busy:
            return
        self.send_preset(
            t(t('Продолжи с места остановки. Посмотри транскрипт выше: что уже сделано, что осталось. Не повторяй завершённые шаги, довыполни оставшееся и проверь результат.')))

    def stop_agent(self):
        """Request cancellation of the running agent turn (этап 35)."""
        if self._cancel_event is not None:
            self._cancel_event.set()
        self.log_activity(t(t('⏹ останавливаю агента…')), "err")
        self.status_var.set(t(t('Остановка…')))

    def attach_file(self):
        """Attach a text file into the composer (ChatGPT-desktop 📎 pattern)."""
        from pathlib import Path
        from tkinter import filedialog

        path = filedialog.askopenfilename(parent=self)
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            messagebox.showerror(t(t('Файл')), str(exc), parent=self)
            return
        snippet = text[:12000]
        self.input.insert(
            "end",
            t(t('\n\nФайл: {v1}\n```\n{snippet}\n```\n')).format(
                v1=Path(path).name, snippet=snippet))
        self.log_activity(t(t('Вложен файл: ')) + Path(path).name)

    # ----------------------------------------------------------------- send
    def send(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self.send_preset(text)

    def send_preset(self, text: str):
        if self._busy:
            messagebox.showinfo(t(t('Чат')), t(t('Дождитесь завершения ответа.')), parent=self)
            return
        try:
            mentor = self.app.mentor_client()
        except MentorError as exc:
            messagebox.showerror(t(t('ИИ-наставник')), str(exc), parent=self)
            self.app.show_page("settings")
            return

        root = self.app.workspace_root()
        workspace = None
        if root is not None:
            try:
                workspace = WorkspaceTools(root, backup_dir=self.app.backup_dir())
            except Exception as exc:
                self.log_activity(t(t('ошибка рабочей папки: {exc}')).format(exc=exc), "err")

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
            max_steps=max(4, min(int(getattr(settings, "agent_max_steps", 20) or 20), 40)),
        )

        self._busy = True
        self._cancel_event = threading.Event()
        self.send_btn.configure(state="disabled")
        try:
            self.stop_btn.configure(state="normal")
        except Exception:
            pass

        def done(value):
            self._busy = False
            self.send_btn.configure(state="normal")
            try:
                self.stop_btn.configure(state="disabled")
            except Exception:
                pass
            reply = value
            self._last_question = text
            self._last_answer = reply.text or ""
            self._last_usage = dict(getattr(reply, "usage", {}) or {})
            try:
                _total = int(self._last_usage.get("total_tokens", 0) or 0)
                if not _total:
                    _total = (int(self._last_usage.get("prompt_tokens", 0) or 0)
                              + int(self._last_usage.get(
                                  "completion_tokens", 0) or 0))
                self.app._tokens_today = int(
                    getattr(self.app, "_tokens_today", 0) or 0) + _total
                self.app.refresh_status_badges()
            except Exception:
                pass
            self._last_model = str(getattr(reply, "model", "") or "")
            for item in transcript:
                self.session.messages.append(ChatMessage.from_dict(item))
            self.session.add("assistant", reply.text)
            self.store.save(self.session)
            self._maybe_save_report(reply.text)
            self._render_messages()
            self.refresh_sessions()
            if "Остановлено пользователем" in (reply.text or ""):
                try:
                    self.resume_btn.configure(state="normal")
                except Exception:
                    pass
            if getattr(settings, "critic_enabled", False) and reply.text:
                self.run_critique_last()

        def failed(_error: str):
            self._busy = False
            self.send_btn.configure(state="normal")
            try:
                self.stop_btn.configure(state="disabled")
            except Exception:
                pass
            for item in transcript:
                self.session.messages.append(ChatMessage.from_dict(item))
            self.store.save(self.session)
            self._render_messages()

        def work():
            from .roles import can as role_can

            guest = not role_can(getattr(settings, "access_role", "owner"),
                                 "mutate")
            common = dict(
                confirm=None if autonomy == "agent" else (
                    lambda name, args, desc: self.app.confirm_from_worker(
                        t(t('Действие наставника')), t(t('{desc}\n\nПодтвердить выполнение?')).format(desc=desc))),
                on_event=lambda kind, payload: self.app.post_event(
                    "chat_event", {"kind": kind, "payload": payload}),
                max_tokens=int(settings.mentor_max_tokens),
                temperature=float(settings.mentor_temperature),
                transcript=transcript,
                cancel_event=self._cancel_event,
            )
            system_extra = str(getattr(settings, "agent_system_extra", "") or "")
            if autonomy == "agent":
                return agent.run_goal(text, **common, system_extra=system_extra,
                                      verify=bool(getattr(settings, "agent_verify", True)),
                                      readonly=guest)
            return agent.run_turn(history, **common, system_extra=system_extra,
                                  readonly=guest)

        self.app.start_async(t(t('Ответ наставника')), work, done, failed)

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
            t(t('Сохранена оценка наставника'))
            + (f" ({report.score:g}/10)" if report.score is not None else ""),
        )
        self.log_activity(t(t('оценка сохранена в «Модель и прогресс»')), "ok")
