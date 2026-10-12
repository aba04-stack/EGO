"""Tkinter desktop shell: sidebar navigation, pages, status bar, event loop."""
from __future__ import annotations

import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

from . import ui_common
from .cloud_gpu import RunPodClient
from .config import AppSettings, SecretStore
from .git_manager import GitRepositoryManager
from .mentor import ApiMentor, MentorError
from .models_registry import ModelRegistry, default_library_dir
from .training import TrainingRun
from .ui_common import C, F_NAV, F_NAV_SMALL, confirm_from_worker


class TrainingHubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AlterEgo Training Hub")
        self.geometry("1320x840")
        self.minsize(1080, 700)

        self.settings = AppSettings.load()
        self.secrets = SecretStore()
        self.git = GitRepositoryManager(timeout_seconds=600)
        self.training = TrainingRun()
        self.events: queue.Queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="alterego-hub")
        self._closing = False
        self._nav_buttons: dict[str, tk.Label] = {}
        self._nav_accent: dict[str, tk.Frame] = {}
        self.pages: dict[str, tk.Frame] = {}

        ui_common.apply_theme(self)
        self._build_layout()
        self._poll_events()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ layout
    def _build_layout(self):
        container = tk.Frame(self, bg=C["bg"])
        container.pack(fill="both", expand=True)

        # Status bar first so it stays at the bottom.
        self.status_bar = tk.Frame(self, bg="#e8edf5")
        self.status_bar.pack(side="bottom", fill="x")
        self.status_text = tk.StringVar(value="Готово")
        tk.Label(self.status_bar, textvariable=self.status_text, bg="#e8edf5",
                 fg=C["muted"], font=ui_common.F_SMALL, anchor="w",
                 padx=12).pack(side="left", fill="x", expand=True)
        self.workspace_badge = tk.StringVar(value="папка не выбрана")
        tk.Label(self.status_bar, textvariable=self.workspace_badge, bg="#e8edf5",
                 fg=C["muted"], font=ui_common.F_SMALL, padx=12).pack(side="right")

        # Sidebar
        sidebar = tk.Frame(container, bg=C["sidebar"], width=230)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=C["sidebar"])
        brand.pack(fill="x", pady=(22, 18), padx=18)
        tk.Label(brand, text="AlterEgo", bg=C["sidebar"], fg="#ffffff",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(brand, text="Training Hub", bg=C["sidebar"], fg=C["sidebar_fg"],
                 font=("Segoe UI", 11)).pack(anchor="w")

        nav_items = [
            ("chat", "Чат с наставником"),
            ("workspace", "Рабочая папка"),
            ("models", "Модели"),
            ("training", "Обучение"),
            ("gpu", "Внешние GPU"),
            ("settings", "Настройки"),
        ]
        for key, label in nav_items:
            self._make_nav_item(sidebar, key, label)

        tk.Label(sidebar, text="v0.2 · локальный контур", bg=C["sidebar"],
                 fg="#5b6b85", font=F_NAV_SMALL).pack(side="bottom", pady=16)

        # Pages area
        self.pages_host = tk.Frame(container, bg=C["bg"])
        self.pages_host.pack(side="left", fill="both", expand=True)

        from .ui_chat import ChatPage
        from .ui_gpu import GpuPage
        from .ui_models import ModelsPage
        from .ui_settings import SettingsPage
        from .ui_training import TrainingPage
        from .ui_workspace import WorkspacePage

        page_classes = [
            ("chat", ChatPage),
            ("workspace", WorkspacePage),
            ("models", ModelsPage),
            ("training", TrainingPage),
            ("gpu", GpuPage),
            ("settings", SettingsPage),
        ]
        for key, cls in page_classes:
            page = cls(self.pages_host, self)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page

        self.show_page("chat")
        self._refresh_workspace_badge()

    def _make_nav_item(self, parent, key: str, label: str):
        row = tk.Frame(parent, bg=C["sidebar"])
        row.pack(fill="x")
        accent = tk.Frame(row, bg=C["sidebar"], width=4)
        accent.pack(side="left", fill="y")
        btn = tk.Label(row, text="  " + label, bg=C["sidebar"], fg=C["sidebar_fg"],
                       font=F_NAV, anchor="w", padx=10, pady=11, cursor="hand2")
        btn.pack(side="left", fill="x", expand=True)

        def on_enter(_event, b=btn, k=key):
            if self._current_page != k:
                b.configure(bg=C["sidebar_hover"])

        def on_leave(_event, b=btn, k=key):
            if self._current_page != k:
                b.configure(bg=C["sidebar"])

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<Button-1>", lambda _event, k=key: self.show_page(k))
        self._nav_buttons[key] = btn
        self._nav_accent[key] = accent

    _current_page = "chat"

    def show_page(self, key: str):
        self._current_page = key
        for name, button in self._nav_buttons.items():
            active = name == key
            button.configure(
                bg=C["sidebar_active"] if active else C["sidebar"],
                fg=C["sidebar_fg_active"] if active else C["sidebar_fg"],
            )
            self._nav_accent[name].configure(bg=C["accent"] if active else C["sidebar"])
        page = self.pages.get(key)
        if page is not None:
            page.lift()
            on_show = getattr(page, "on_show", None)
            if callable(on_show):
                on_show()

    # ------------------------------------------------------------- services
    def post_event(self, kind: str, payload: dict):
        if self._closing:
            # Never leave a worker blocked on confirmation after shutdown.
            if kind == "confirm":
                payload["box"]["ok"] = False
                payload["event"].set()
            return
        self.events.put((kind, payload))

    def start_async(self, label: str, task, on_success=None, on_error=None):
        self.set_status(label + "…")

        def work():
            try:
                result = task()
                self.post_event("result", {"ok": True, "label": label, "value": result,
                                           "callback": on_success})
            except Exception as exc:  # noqa: BLE001 - shown to the user in a dialog
                self.post_event("result", {"ok": False, "label": label, "error": str(exc),
                                           "on_error": on_error})

        try:
            self.executor.submit(work)
        except RuntimeError:
            self.set_status("Приложение закрывается")

    def set_status(self, text: str):
        self.status_text.set(text)

    def _poll_events(self):
        if self._closing:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _handle_event(self, kind: str, payload: dict):
        if kind == "confirm":
            answer = messagebox.askyesno(payload.get("title", "Подтверждение"),
                                         payload.get("message", ""), parent=self)
            payload["box"]["ok"] = answer
            payload["event"].set()
            return
        if kind == "info":
            messagebox.showinfo(payload.get("title", "AlterEgo Training Hub"),
                                payload.get("message", ""), parent=self)
            return
        if kind == "chat_event":
            chat = self.pages.get("chat")
            handler = getattr(chat, "on_agent_event", None)
            if callable(handler):
                handler(payload.get("kind", ""), payload.get("payload", {}))
            return
        if kind == "result":
            if payload.get("ok"):
                self.set_status("Готово: " + str(payload.get("label", "")))
                callback = payload.get("callback")
                if callback:
                    try:
                        callback(payload.get("value"))
                    except Exception as exc:  # noqa: BLE001
                        self.set_status("Ошибка обработки результата")
                        messagebox.showerror("AlterEgo Training Hub",
                                             f"Операция завершилась, но интерфейс не смог "
                                             f"обновить результат: {exc}", parent=self)
            else:
                self.set_status("Ошибка: " + str(payload.get("label", "")))
                messagebox.showerror("AlterEgo Training Hub",
                                     str(payload.get("error", "Неизвестная ошибка")),
                                     parent=self)
                on_error = payload.get("on_error")
                if on_error:
                    try:
                        on_error(payload.get("error", ""))
                    except Exception:  # noqa: BLE001 - UI recovery must not cascade
                        pass

    # -------------------------------------------------------------- helpers
    def save_settings(self):
        self.settings.save()
        self._refresh_workspace_badge()

    def _refresh_workspace_badge(self):
        path = (self.settings.workspace_path or "").strip()
        self.workspace_badge.set(f"папка: {Path(path).name}" if path else "папка не выбрана")

    def workspace_root(self) -> Path | None:
        raw = (self.settings.workspace_path or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        return path if path.is_dir() else None

    def mentor_client(self) -> ApiMentor:
        base_url = (self.settings.mentor_base_url or "").strip()
        model = (self.settings.mentor_model or "").strip()
        key = self.secrets.get("mentor_api_key") if base_url and model else ""
        if not base_url or not model or not key:
            raise MentorError(
                "Настройте провайдера, модель и API-ключ на странице «Настройки»."
            )
        return ApiMentor(base_url, model, key)

    def model_registry(self) -> ModelRegistry:
        raw = (self.settings.model_library_path or "").strip()
        library = Path(raw).expanduser() if raw else default_library_dir()
        return ModelRegistry(library)

    def runpod_client(self) -> RunPodClient:
        key = self.secrets.get("runpod_api_key")
        return RunPodClient(key)

    def confirm_from_worker(self, title: str, message: str) -> bool:
        return confirm_from_worker(self, title, message)

    def request_confirmation(self, title: str, message: str) -> bool:
        return messagebox.askyesno(title, message, parent=self)

    # ---------------------------------------------------------------- close
    def _on_close(self):
        self._closing = True
        try:
            self.training.stop()
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main():
    app = TrainingHubApp()
    app.mainloop()
