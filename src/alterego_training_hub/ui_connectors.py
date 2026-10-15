"""Connectors page: GitHub, Hugging Face, Gmail — status, secrets, test actions."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from .connectors import ConnectorManager
from .i18n import t
from .ui_common import (
    F_BASE,
    F_MONO,
    F_SMALL,
    C,
    Collapsible,
    card,
    page_header,
    set_text,
)


class ConnectorsPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self._build()

    def _manager(self) -> ConnectorManager:
        return ConnectorManager(self.app.secrets,
                                gmail_from=self.app.settings.gmail_from)

    def _build(self):
        header = page_header(
            self,
            t(t('Коннекторы')),
            t(t('Сервисы, которые помогают разработке: GitHub, Hugging Face, Gmail. Токены хранятся только в системном хранилище; агент-наставник использует коннекторы как инструменты.')),
        )
        header.pack(fill="x", padx=24, pady=(20, 12))

        self.cards: dict[str, dict] = {}
        for spec in self._manager().specs():
            frame = card(self, f"{spec.title}")
            frame.pack(fill="x", padx=24, pady=(0, 10))
            tk.Label(frame, text=spec.description, bg=C["panel"], fg=C["muted"],
                     font=F_SMALL, wraplength=900, justify="left").pack(anchor="w")
            row = tk.Frame(frame, bg=C["panel"])
            row.pack(fill="x", pady=(6, 0))
            tk.Label(row, text=spec.secret_label, bg=C["panel"], font=F_BASE).pack(
                side="left", padx=(0, 8))
            secret_var = tk.StringVar()
            tk.Entry(row, textvariable=secret_var, show="•", bd=1, relief="solid",
                     font=F_BASE, width=36).pack(side="left")
            status_var = tk.StringVar()
            tk.Label(row, textvariable=status_var, bg=C["panel"], fg=C["muted"],
                     font=F_SMALL).pack(side="left", padx=10)
            ttk.Button(row, text=t(t('Сохранить')),
                       command=lambda s=spec.id, v=secret_var, st=status_var:
                       self.save_secret(s, v, st)).pack(side="left")
            ttk.Button(row, text=t(t('Удалить')), style="Danger.TButton",
                       command=lambda s=spec.id, v=secret_var, st=status_var:
                       self.delete_secret(s, v, st)).pack(side="left", padx=6)
            self.cards[spec.id] = {"status": status_var, "secret": secret_var}

        # Actions
        actions_section = Collapsible(self, t(t('Действия')))
        actions_section.pack(fill="x", padx=24, pady=(0, 10))
        actions = actions_section.body
        row1 = tk.Frame(actions, bg=C["panel"])
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text=t(t('GitHub / HF поиск')), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 8))
        self.query_var = tk.StringVar(value="llm training")
        tk.Entry(row1, textvariable=self.query_var, bd=1, relief="solid",
                 font=F_BASE, width=30).pack(side="left", padx=(0, 8))
        ttk.Button(row1, text=t(t('GitHub репозитории')),
                   command=self.search_github).pack(side="left", padx=4)
        ttk.Button(row1, text=t(t('HF модели')),
                   command=self.search_huggingface).pack(side="left", padx=4)

        row2 = tk.Frame(actions, bg=C["panel"])
        row2.pack(fill="x", pady=(6, 2))
        tk.Label(row2, text=t(t('Письмо: кому')), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.mail_to = tk.StringVar()
        tk.Entry(row2, textvariable=self.mail_to, bd=1, relief="solid", width=24,
                 font=F_BASE).pack(side="left", padx=(0, 8))
        tk.Label(row2, text=t(t('отправитель')), bg=C["panel"], font=F_BASE).pack(
            side="left", padx=(0, 6))
        self.mail_from = tk.StringVar(value=self.app.settings.gmail_from)
        tk.Entry(row2, textvariable=self.mail_from, bd=1, relief="solid", width=24,
                 font=F_BASE).pack(side="left", padx=(0, 8))
        ttk.Button(row2, text=t(t('Тест письма')),
                   command=self.send_test_mail).pack(side="left", padx=4)

        self.results = tk.Text(self, height=9, wrap="word", state="disabled",
                               bd=1, relief="solid", font=F_MONO)
        self.results.pack(fill="both", expand=True, padx=24, pady=(0, 14))
        self.refresh_status()

    # ------------------------------------------------------------- handlers
    def refresh_status(self):
        manager = self._manager()
        for spec in manager.specs():
            status = manager.status(spec.id)
            self.cards[spec.id]["status"].set(status["state"])

    def on_show(self):
        self.refresh_status()

    def save_secret(self, connector_id, secret_var, status_var):
        value = secret_var.get().strip()
        if not value:
            messagebox.showinfo(t(t('Коннекторы')), t(t('Введите значение.')), parent=self)
            return
        try:
            self._manager().set_secret(connector_id, value)
        except Exception as exc:
            messagebox.showerror(t(t('Коннекторы')), str(exc), parent=self)
            return
        secret_var.set("")
        self.refresh_status()

    def delete_secret(self, connector_id, secret_var, status_var):
        try:
            self._manager().delete_secret(connector_id)
        except Exception as exc:
            messagebox.showerror(t(t('Коннекторы')), str(exc), parent=self)
            return
        secret_var.set("")
        self.refresh_status()

    def search_github(self):
        self.app.start_async(
            t(t('Поиск на GitHub')),
            lambda: self._manager().github_search(self.query_var.get()),
            lambda rows: set_text(self.results,
                                  json.dumps(rows, ensure_ascii=False, indent=2)),
        )

    def search_huggingface(self):
        self.app.start_async(
            t(t('Поиск на Hugging Face')),
            lambda: self._manager().huggingface_search(self.query_var.get()),
            lambda rows: set_text(self.results,
                                  json.dumps(rows, ensure_ascii=False, indent=2)),
        )

    def send_test_mail(self):
        self.app.settings.gmail_from = self.mail_from.get().strip()
        self.app.save_settings()
        if not messagebox.askyesno(
            t(t('Отправить письмо')),
            t(t('Отправить тестовое письмо на {v1}?')).format(v1=self.mail_to.get().strip()),
            parent=self,
        ):
            return

        def done(result):
            messagebox.showinfo(t(t('Коннекторы')),
                                t(t('Письмо отправлено: {v1}')).format(v1=result.get('to')),
                                parent=self)

        self.app.start_async(
            t(t('Отправка письма')),
            lambda: self._manager().gmail_send(
                self.mail_to.get().strip(),
                t(t('AlterEgo Training Hub — тест')),
                t(t('Тестовое уведомление от AlterEgo Training Hub.')),
            ),
            done,
        )
