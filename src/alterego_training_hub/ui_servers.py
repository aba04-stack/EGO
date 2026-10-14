"""Servers page: connect remote machines over SSH, inspect and run commands."""
from __future__ import annotations
from .i18n import t

import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .servers import ServerEntry, ServerError, ServerManager
from .ui_common import C, F_BASE, F_MONO, F_SMALL, Collapsible, page_header, set_text


class ServersPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._entries: list[ServerEntry] = []
        self._build()

    def _manager(self) -> ServerManager:
        return self.app.server_manager()

    def _build(self):
        header = page_header(
            self,
            t('Серверы'),
            t('Подключение удалённых серверов по SSH: проверка связи, состояние системы и выполнение команд — вручную или через агента-наставника. Пароли хранятся только в системном хранилище.'),
        )
        header.pack(fill="x", padx=24, pady=(20, 10))

        form = Collapsible(self, t('Настройки подключения'))
        form.pack(fill="x", padx=24, pady=(0, 10))
        form.set_hint(t('свернуть/развернуть'))
        body = form.body
        body.columnconfigure(1, weight=1)

        self.var_name = tk.StringVar()
        self.var_host = tk.StringVar()
        self.var_port = tk.StringVar(value="22")
        self.var_user = tk.StringVar()
        self.var_auth = tk.StringVar(value="key")
        self.var_key = tk.StringVar()
        self.var_password = tk.StringVar()

        rows = [
            (t('Имя'), self.var_name, 24),
            (t('Хост (IP / домен)'), self.var_host, 28),
            (t('Порт'), self.var_port, 6),
            (t('SSH-пользователь'), self.var_user, 18),
        ]
        for row, (label, var, width) in enumerate(rows):
            tk.Label(body, text=label, bg=C["panel"], font=F_BASE).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            tk.Entry(body, textvariable=var, width=width, bd=1, relief="solid",
                     font=F_BASE).grid(row=row, column=1, sticky="w", pady=4)

        auth_row = tk.Frame(body, bg=C["panel"])
        auth_row.grid(row=0, column=2, sticky="w", padx=(16, 0), pady=4)
        tk.Label(auth_row, text=t('Авторизация'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        ttk.Combobox(auth_row, textvariable=self.var_auth, width=10,
                     state="readonly", values=("key", "password")).pack(side="left")

        key_row = tk.Frame(body, bg=C["panel"])
        key_row.grid(row=1, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=4)
        tk.Label(key_row, text=t('Файл ключа (необязательно)'), bg=C["panel"],
                 font=F_BASE).pack(side="left", padx=(0, 8))
        tk.Entry(key_row, textvariable=self.var_key, width=28, bd=1,
                 relief="solid", font=F_BASE).pack(side="left", padx=(0, 6))
        ttk.Button(key_row, text=t('Обзор…'), width=8,
                   command=self.pick_key).pack(side="left")

        pass_row = tk.Frame(body, bg=C["panel"])
        pass_row.grid(row=2, column=2, columnspan=2, sticky="w", padx=(16, 0), pady=4)
        tk.Label(pass_row, text=t('Пароль SSH'), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        tk.Entry(pass_row, textvariable=self.var_password, show="•", width=24,
                 bd=1, relief="solid", font=F_BASE).pack(side="left", padx=(0, 8))
        self.secret_status = tk.StringVar(value="")
        tk.Label(pass_row, textvariable=self.secret_status, bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left")
        tk.Label(pass_row, text=t('«key» — вход по ключу/агенту; «password» — пароль из системного хранилища'), bg=C["panel"],
                 fg=C["muted"], font=F_SMALL).pack(side="left", padx=8)

        actions = tk.Frame(body, bg=C["panel"])
        actions.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(actions, text=t('Сохранить сервер'), style="Accent.TButton",
                   command=self.save_server).pack(side="left")
        ttk.Button(actions, text=t('Удалить'), style="Danger.TButton",
                   command=self.delete_server).pack(side="left", padx=8)
        ttk.Button(actions, text=t('Проверить подключение'),
                   command=self.test_connection).pack(side="left", padx=8)
        ttk.Button(actions, text=t('Информация о сервере'),
                   command=self.show_info).pack(side="left", padx=8)

        # Server list
        list_card = Collapsible(self, t('Подключённые серверы'))
        list_card.pack(fill="x", padx=24, pady=(0, 10))
        columns = ("name", "address", "auth", "status")
        self.tree = ttk.Treeview(list_card.body, columns=columns,
                                 show="headings", height=5)
        for col, title, width in [
            ("name", t('Имя'), 120), ("address", t('Адрес'), 220),
            ("auth", t('Вход'), 90), ("status", t('Состояние'), 260),
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=2, pady=2)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._load_selected())

        # Remote command row
        cmd_card = Collapsible(self, t('Команда на сервере'))
        cmd_card.pack(fill="x", padx=24, pady=(0, 10))
        row = tk.Frame(cmd_card.body, bg=C["panel"])
        row.pack(fill="x")
        self.cmd_var = tk.StringVar()
        tk.Entry(row, textvariable=self.cmd_var, bd=1, relief="solid",
                 font=F_MONO).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row, text=t('▶ Выполнить'), style="Accent.TButton",
                   command=self.run_remote).pack(side="left")
        ttk.Button(row, text=t('Очистить'),
                   command=lambda: set_text(self.results, "")).pack(side="left",
                                                                   padx=8)
        self.results = tk.Text(self, height=9, wrap="word", state="disabled",
                               bd=1, relief="solid", font=F_MONO)
        self.results.pack(fill="both", expand=True, padx=24, pady=(0, 14))

        self.refresh_list()

    # ------------------------------------------------------------- handlers
    def pick_key(self):
        path = filedialog.askopenfilename(
            parent=self, title=t('Файл SSH-ключа'))
        if path:
            self.var_key.set(path)

    def _selected_entry(self) -> ServerEntry | None:
        selection = self.tree.selection()
        if not selection:
            return None
        item_id = selection[0]
        return next((entry for entry in self._entries if entry.id == item_id), None)

    def _load_selected(self):
        entry = self._selected_entry()
        if entry is None:
            return
        self.var_name.set(entry.name)
        self.var_host.set(entry.host)
        self.var_port.set(str(entry.port))
        self.var_user.set(entry.user)
        self.var_auth.set(entry.auth_kind)
        self.var_key.set(entry.key_path)
        self.var_password.set("")
        try:
            manager = self._manager()
            self.secret_status.set(
                t('пароль сохранён') if manager.has_password(entry.id) else t('пароль не сохранён'))
        except Exception:
            self.secret_status.set("")

    def refresh_list(self, status_by_id: dict[str, str] | None = None):
        status_by_id = status_by_id or {}
        try:
            self._entries = self._manager().list()
        except Exception:
            self._entries = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        for entry in self._entries:
            self.tree.insert("", "end", iid=entry.id, values=(
                entry.name, entry.address, entry.auth_kind,
                status_by_id.get(entry.id, "")))
        if self._entries:
            self.tree.selection_set(self._entries[0].id)

    def on_show(self):
        self.refresh_list()

    def _entry_from_form(self) -> ServerEntry:
        entry = self._selected_entry() or ServerEntry()
        entry.name = self.var_name.get()
        entry.host = self.var_host.get()
        entry.port = int(self.var_port.get().strip() or 22)
        entry.user = self.var_user.get()
        entry.auth_kind = self.var_auth.get().strip() or "key"
        entry.key_path = self.var_key.get()
        return entry

    def save_server(self):
        try:
            entry = self._entry_from_form()
            entry.validate()
            manager = self._manager()
            manager.save(entry)
            password = self.var_password.get().strip()
            if entry.auth_kind == "password" and password:
                manager.set_password(entry.id, password)
            self.var_password.set("")
        except (ServerError, ValueError) as exc:
            messagebox.showerror(t('Серверы'), str(exc), parent=self)
            return
        except Exception as exc:  # keyring etc.
            messagebox.showerror(t('Серверы'), t('Не удалось сохранить: {exc}').format(exc=exc),
                                 parent=self)
            return
        self.refresh_list()
        self.app.refresh_terminal_targets()
        self.app.activity.log("server", t('Сохранён сервер: {v1}').format(v1=entry.name))

    def delete_server(self):
        entry = self._selected_entry()
        if entry is None:
            messagebox.showinfo(t('Серверы'), t('Выберите сервер в списке.'), parent=self)
            return
        if not messagebox.askyesno(t('Удалить сервер'),
                                   t('Удалить «{v1}»?').format(v1=entry.name), parent=self):
            return
        try:
            self._manager().delete(entry.id)
        except Exception as exc:
            messagebox.showerror(t('Серверы'), str(exc), parent=self)
            return
        self.refresh_list()
        self.app.refresh_terminal_targets()

    def test_connection(self):
        entry = self._selected_entry()
        if entry is not None:
            task = lambda: self._manager().test_connection(entry.id)  # noqa: E731
            label = entry.name
        else:
            try:
                entry = self._entry_from_form()
                entry.validate()
            except (ServerError, ValueError) as exc:
                messagebox.showerror(t('Серверы'), str(exc), parent=self)
                return
            task = lambda: self._test_unsaved(entry)  # noqa: E731
            label = entry.name or entry.host

        def done(result):
            stamp = time.strftime("%H:%M:%S")
            mark = "ok" if result.get("ok") else t('ошибка')
            set_text(self.results,
                     f"[{stamp}] {label}: {mark}\n" + str(result.get("output", "")))
            self.refresh_list({entry.id: mark})

        self.app.start_async(t('Проверка: {label}').format(label=label), task, done)

    def _test_unsaved(self, entry: ServerEntry) -> dict:
        manager = self._manager()
        secret = self.var_password.get().strip() if entry.auth_kind == "password" else ""
        runner = manager.runner_factory(entry, secret)
        runner.connect()
        try:
            return runner.run("echo connected && hostname", timeout=20)
        finally:
            runner.close()

    def show_info(self):
        entry = self._selected_entry()
        if entry is None:
            messagebox.showinfo(t('Серверы'), t('Выберите сервер в списке.'), parent=self)
            return

        def done(result):
            set_text(self.results, str(result.get("info", result.get("output", ""))))

        self.app.start_async(t('Информация: {v1}').format(v1=entry.name),
                             lambda: self._manager().info(entry.id), done)

    def run_remote(self):
        entry = self._selected_entry()
        command = self.cmd_var.get().strip()
        if entry is None:
            messagebox.showinfo(t('Серверы'), t('Выберите сервер в списке.'), parent=self)
            return
        if not command:
            return

        def done(result):
            stamp = time.strftime("%H:%M:%S")
            self.results.configure(state="normal")
            self.results.insert("end",
                                t('\n$ {command}\n{v3}\n[код {v5} · {stamp}]\n').format(command=command, v3=result.get('output', ''), v5=result.get('exit_code', '?'), stamp=stamp))
            self.results.configure(state="disabled")
            self.results.see("end")

        self.app.start_async(
            t('Команда на {v1}').format(v1=entry.name),
            lambda: self._manager().run_command(entry.id, command),
            done,
        )
