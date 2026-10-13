"""Tkinter IDE shell: sidebar, center workspace, bottom terminal, right chat."""
from __future__ import annotations

import json
import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

from . import ui_common
from .activity import ActivityLog
from .agent import MODEL_TOOLS_SCHEMAS, TRAINING_CONTEXT_TOOL_SCHEMAS
from .cloud_gpu import RunPodClient
from .config import AppSettings, SecretStore, app_data_dir
from .connectors import ConnectorManager
from .diagnostics import diagnostics_summary, diagnostics_text, run_diagnostics
from .git_manager import GitRepositoryManager
from .logging_setup import install_excepthook, log_worker_error, setup_logging
from .mentor import ApiMentor, MentorError
from .metrics import brief as metrics_brief, parse_log
from .models_registry import ModelRegistry, default_library_dir
from .report import REPORT_PROMPT_TEMPLATE, ReportStore
from .runs import RunStore
from .servers import ServerManager, ServerStore
from .training import TrainingRun
from .ui_common import C, F_NAV, F_NAV_SMALL, confirm_from_worker


class TrainingHubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        setup_logging()
        install_excepthook()
        self.title("AlterEgo Training Hub — LLM Studio")
        self.geometry("1480x860")
        self.minsize(1180, 720)

        self.settings = AppSettings.load()
        from .theme import PALETTES, set_palette

        set_palette(self.settings.ui_theme
                    if self.settings.ui_theme in PALETTES else "light")
        self.secrets = SecretStore()
        self.git = GitRepositoryManager(timeout_seconds=600)
        self.training = TrainingRun()
        self.runs = RunStore()
        self.activity = ActivityLog()
        self.reports = ReportStore()
        self.servers = ServerStore()
        self.events: queue.Queue = queue.Queue()
        self.agent_plan: list[str] = []
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
        self.status_bar = tk.Frame(self, bg=C["statusbar"])
        self.status_bar.pack(side="bottom", fill="x")
        self.status_text = tk.StringVar(value="Готово")
        tk.Label(self.status_bar, textvariable=self.status_text, bg=C["statusbar"],
                 fg=C["muted"], font=ui_common.F_SMALL, anchor="w",
                 padx=12).pack(side="left", fill="x", expand=True)
        self.workspace_badge = tk.StringVar(value="папка не выбрана")
        tk.Label(self.status_bar, textvariable=self.workspace_badge,
                 bg=C["statusbar"],
                 fg=C["muted"], font=ui_common.F_SMALL, padx=12).pack(side="right")
        self.git_badge = tk.StringVar(value="")
        tk.Label(self.status_bar, textvariable=self.git_badge, bg=C["statusbar"],
                 fg=C["muted"], font=ui_common.F_SMALL, padx=12).pack(side="right")

        container = tk.Frame(self, bg=C["bg"])
        container.pack(fill="both", expand=True)

        # ---- Left sidebar (navigation) --------------------------------
        sidebar = tk.Frame(container, bg=C["sidebar"], width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=C["sidebar"])
        brand.pack(fill="x", pady=(18, 12), padx=16)
        tk.Label(brand, text="AlterEgo", bg=C["sidebar"], fg="#ffffff",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(brand, text="LLM Studio", bg=C["sidebar"], fg=C["sidebar_fg"],
                 font=("Segoe UI", 10)).pack(anchor="w")

        nav_groups = [
            ("РАЗРАБОТКА", [
                ("editor", "Редактор кода"),
                ("workspace", "Рабочая папка"),
                ("search", "Поиск"),
            ]),
            ("БИБЛИОТЕКА", [
                ("models", "Модели"),
                ("datasets", "Датасеты"),
                ("model", "Модель и прогресс"),
            ]),
            ("ЭКСПЕРИМЕНТЫ", [
                ("playground", "Playground"),
                ("training", "Обучение"),
                ("gpu", "Внешние GPU"),
            ]),
            ("СИСТЕМА", [
                ("servers", "Серверы"),
                ("connectors", "Коннекторы"),
                ("settings", "Настройки"),
            ]),
        ]
        for group_title, items in nav_groups:
            tk.Label(sidebar, text=group_title, bg=C["sidebar"], fg="#5b6b85",
                     font=F_NAV_SMALL, anchor="w", padx=16).pack(fill="x",
                                                                 pady=(10, 2))
            for key, label in items:
                self._make_nav_item(sidebar, key, label)

        tk.Label(sidebar, text="v0.5 · локальный контур", bg=C["sidebar"],
                 fg="#5b6b85", font=F_NAV_SMALL).pack(side="bottom", pady=12)

        # ---- Right chat panel (docked) --------------------------------
        from .ui_chat import ChatPage

        self.chat_panel = ChatPage(container, self)
        self.chat_panel.pack(side="right", fill="y")
        self.chat_panel.configure(width=390)
        self.chat_panel.pack_propagate(False)

        # ---- Center: pages + terminal ---------------------------------
        center = tk.Frame(container, bg=C["bg"])
        center.pack(side="left", fill="both", expand=True)
        self.pages_host = tk.Frame(center, bg=C["bg"])
        self.pages_host.pack(fill="both", expand=True)

        from .ui_datasets import DatasetsPage
        from .ui_editor import EditorPage
        from .ui_gpu import GpuPage
        from .ui_model import ModelDashboardPage
        from .ui_models import ModelsPage
        from .ui_playground import PlaygroundPage
        from .ui_search import SearchPage
        from .ui_servers import ServersPage
        from .ui_settings import SettingsPage
        from .ui_terminal import TerminalPanel
        from .ui_training import TrainingPage
        from .ui_workspace import WorkspacePage
        from .ui_connectors import ConnectorsPage

        page_classes = [
            ("editor", EditorPage),
            ("workspace", WorkspacePage),
            ("search", SearchPage),
            ("models", ModelsPage),
            ("datasets", DatasetsPage),
            ("model", ModelDashboardPage),
            ("playground", PlaygroundPage),
            ("training", TrainingPage),
            ("gpu", GpuPage),
            ("servers", ServersPage),
            ("connectors", ConnectorsPage),
            ("settings", SettingsPage),
        ]
        for key, cls in page_classes:
            page = cls(self.pages_host, self)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page
        self.pages["chat"] = self.chat_panel

        # Bottom panel: ТЕРМИНАЛ / ПРОБЛЕМЫ / ГИТ tabs (VS Code style)
        from .ui_git import GitPanel
        from .ui_problems import ProblemsPanel

        self.bottom = tk.Frame(center, bg=C["panel"])
        self.bottom.pack(side="bottom", fill="x", pady=(0, 2))
        self.bottom.configure(height=210)
        self.bottom.pack_propagate(False)
        bottom_bar = tk.Frame(self.bottom, bg=C["panel"])
        bottom_bar.pack(fill="x")
        self._bottom_view = "terminal"
        self._bottom_visible = True
        self.terminal_tab = tk.Label(bottom_bar, text="ТЕРМИНАЛ", bg=C["panel"],
                                     fg=C["accent"], font=F_NAV_SMALL, padx=12,
                                     pady=6, cursor="hand2")
        self.terminal_tab.pack(side="left")
        self.terminal_tab.bind("<Button-1>",
                               lambda _e: self.show_bottom("terminal"))
        self.problems_tab = tk.Label(bottom_bar, text="ПРОБЛЕМЫ", bg=C["panel"],
                                     fg=C["muted"], font=F_NAV_SMALL, padx=12,
                                     pady=6, cursor="hand2")
        self.problems_tab.pack(side="left")
        self.problems_tab.bind("<Button-1>",
                               lambda _e: self.show_bottom("problems"))
        self.git_tab = tk.Label(bottom_bar, text="ГИТ", bg=C["panel"],
                                fg=C["muted"], font=F_NAV_SMALL, padx=12,
                                pady=6, cursor="hand2")
        self.git_tab.pack(side="left")
        self.git_tab.bind("<Button-1>",
                          lambda _e: self.show_bottom("git"))
        tk.Label(bottom_bar, text="Ctrl+J — свернуть панель", bg=C["panel"],
                 fg=C["muted"], font=F_NAV_SMALL, padx=12).pack(side="right")

        self.terminal = TerminalPanel(self.bottom, self)
        self.problems = ProblemsPanel(self.bottom, self)
        self.git_panel = GitPanel(self.bottom, self)
        self.problems_tab.configure(textvariable=self.problems.count_var)
        self.show_bottom("terminal")

        self.show_page("editor")
        self._refresh_workspace_badge()
        self._bind_shortcuts()
        self.set_status("Готово · F1 — горячие клавиши")

    def show_bottom(self, which: str):
        self._bottom_view = which
        panels = {"terminal": self.terminal, "problems": self.problems,
                  "git": self.git_panel}
        for panel in panels.values():
            panel.pack_forget()
        panels.get(which, self.terminal).pack(fill="both", expand=True)
        self.terminal_tab.configure(
            fg=C["accent"] if which == "terminal" else C["muted"])
        self.problems_tab.configure(
            fg=C["accent"] if which == "problems" else C["muted"])
        self.git_tab.configure(
            fg=C["accent"] if which == "git" else C["muted"])
        if which == "problems":
            self.problems.refresh()
        elif which == "git":
            self.git_panel.refresh()

    def toggle_bottom(self):
        self._bottom_visible = not self._bottom_visible
        if self._bottom_visible:
            self.bottom.pack(side="bottom", fill="x", pady=(0, 2))
            self.show_bottom(self._bottom_view or "terminal")
        else:
            self.bottom.pack_forget()

    def _bind_shortcuts(self):
        page_keys = ["editor", "workspace", "models", "datasets", "model",
                     "playground", "training", "gpu", "servers"]
        for index, key in enumerate(page_keys, start=1):
            self.bind_all(f"<Control-Key-{index}>",
                          lambda _e, k=key: self.show_page(k))
        self.bind_all("<Control-Key-0>", lambda _e: self.show_page("settings"))
        self.bind_all("<Control-k>", lambda _e: self.show_page("chat"))
        self.bind_all("<Control-j>", lambda _e: self.toggle_bottom())
        self.bind_all("<Control-Shift-M>",
                      lambda _e: self.show_bottom("problems"))
        self.bind_all("<Control-Shift-m>",
                      lambda _e: self.show_bottom("problems"))
        self.bind_all("<Control-Shift-G>",
                      lambda _e: self.show_bottom("git"))
        self.bind_all("<Control-Shift-g>",
                      lambda _e: self.show_bottom("git"))
        self.bind_all("<Control-p>", lambda _e: self.open_command_palette("files"))
        self.bind_all("<Control-Shift-P>",
                      lambda _e: self.open_command_palette("commands"))
        self.bind_all("<Control-Shift-p>",
                      lambda _e: self.open_command_palette("commands"))
        self.bind_all("<Control-Shift-F>",
                      lambda _e: self.show_page("search"))
        self.bind_all("<Control-Shift-f>",
                      lambda _e: self.show_page("search"))
        self.bind_all("<F5>", lambda _e: self.refresh_current())
        self.bind_all("<F1>", lambda _e: self.show_shortcuts_help())

    def open_command_palette(self, mode: str = "commands"):
        from .ui_palette import open_command_palette

        return open_command_palette(self, mode)

    def refresh_current(self):
        page = self.pages.get(self._current_page)
        on_show = getattr(page, "on_show", None) if page is not None else None
        if callable(on_show):
            on_show()
            self.set_status("Обновлено: " + self._current_page)

    def toggle_theme(self, name: str | None = None):
        """Switch between the light and dark palettes live."""
        from .theme import C as live_colors
        from .theme import PALETTES, current_theme, set_palette

        old = dict(live_colors)
        target = name or ("dark" if current_theme() == "light" else "light")
        if target not in PALETTES:
            target = "light"
        set_palette(target)
        self.settings.ui_theme = target
        self.save_settings()
        ui_common.apply_theme(self)
        ui_common.recolor_widgets(self, old, live_colors)
        page = self.pages.get("settings")
        status = getattr(page, "theme_status", None) if page is not None else None
        if status is not None:
            status.set("Текущая тема: " + ("тёмная" if target == "dark"
                                           else "светлая") + ".")
        self.set_status("Тема: " + ("тёмная" if target == "dark" else "светлая")
                        + " · переключение сохранено")

    def show_shortcuts_help(self):
        messagebox.showinfo(
            "Горячие клавиши",
            "Ctrl+1…Ctrl+9 — страницы (редактор, папка, модели, датасеты,\n"
            "   модель, playground, обучение, GPU, серверы)\n"
            "Ctrl+0 — настройки\n"
            "Ctrl+P — быстрое открытие файла\n"
            "Ctrl+Shift+P — палитра команд\n"
            "Ctrl+Shift+F — поиск по проекту\n"
            "Ctrl+K — фокус в чат наставника\n"
            "Ctrl+J — свернуть/развернуть нижнюю панель\n"
            "Ctrl+Shift+M — панель «Проблемы»\n"
            "Ctrl+W — закрыть вкладку редактора\n"
            "Ctrl+Tab — следующая вкладка редактора\n"
            "Ctrl+F / Ctrl+H — поиск и замена в редакторе\n"
            "F3 / Shift+F3 — следующее/предыдущее совпадение\n"
            "Ctrl+F2 — закладка, F2 / Shift+F2 — между закладками\n"
            "Ctrl+G — перейти к строке; Ctrl+Shift+G — панель Git\n"
            "Ctrl+\\ — разделённый вид; Ctrl++ / Ctrl+- — масштаб шрифта\n"
            "F5 — обновить текущую страницу\n"
            "F1 — эта справка\n"
            "Ctrl+Enter — отправить сообщение в чате\n"
            "Ctrl+S — сохранить файл в редакторе",
            parent=self)

    def _make_nav_item(self, parent, key: str, label: str):
        row = tk.Frame(parent, bg=C["sidebar"])
        row.pack(fill="x")
        accent = tk.Frame(row, bg=C["sidebar"], width=4)
        accent.pack(side="left", fill="y")
        btn = tk.Label(row, text="  " + label, bg=C["sidebar"], fg=C["sidebar_fg"],
                       font=F_NAV, anchor="w", padx=8, pady=8, cursor="hand2")
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

    _current_page = "editor"

    def show_page(self, key: str):
        if key == "chat":
            focus = getattr(self.chat_panel, "focus_input", None)
            if callable(focus):
                focus()
            else:
                self.chat_panel.focus_set()
            return
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
        self._refresh_git_badge()

    # ------------------------------------------------------------- services
    def post_event(self, kind: str, payload: dict):
        if self._closing:
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
                log_worker_error("worker", exc)
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
                try:
                    self._handle_event(kind, payload)
                except Exception as exc:  # noqa: BLE001 - one bad event must not kill the loop
                    self.set_status(f"Ошибка обработки события: {exc}")
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
            handler = getattr(self.chat_panel, "on_agent_event", None)
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
                        log_worker_error("callback", exc)
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
                    except Exception as exc:  # noqa: BLE001 - UI recovery must not cascade
                        log_worker_error("on_error", exc)

    # -------------------------------------------------------------- helpers
    def save_settings(self):
        self.settings.save()
        self._refresh_workspace_badge()

    def _refresh_workspace_badge(self):
        path = (self.settings.workspace_path or "").strip()
        self.workspace_badge.set(f"папка: {Path(path).name}" if path else "папка не выбрана")
        self._refresh_git_badge()

    def _refresh_git_badge(self):
        root = self.workspace_root()
        value = ""
        if root is not None:
            try:
                status = self.git.status(root)
                mark = "*" if status.changes else ""
                extra = f" {status.ahead_behind}" if status.ahead_behind else ""
                value = f"git: {status.branch}{mark}{extra}"
            except Exception:  # noqa: BLE001 - not a repo / git missing
                value = "git: —"
        self.git_badge.set(value)

    def workspace_root(self) -> Path | None:
        raw = (self.settings.workspace_path or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        return path if path.is_dir() else None

    def backup_dir(self) -> Path:
        path = app_data_dir() / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def server_manager(self) -> ServerManager:
        return ServerManager(self.servers, self.secrets)

    def refresh_terminal_targets(self):
        terminal = getattr(self, "terminal", None)
        if terminal is not None:
            terminal.refresh_targets()

    def mentor_client(self) -> ApiMentor:
        base_url = (self.settings.mentor_base_url or "").strip()
        model = (self.settings.mentor_model or "").strip()
        try:
            key = self.secrets.get("mentor_api_key") if base_url and model else ""
        except RuntimeError as exc:
            raise MentorError(str(exc)) from None
        if not base_url or not model or not key:
            raise MentorError(
                "Настройте провайдера, модель и API-ключ на странице «Настройки»."
            )
        from .mentor import build_mentor

        return build_mentor(
            provider=self.settings.llm_provider,
            base_url=base_url,
            model=model,
            api_key=key,
            reasoning_effort=self.settings.agent_reasoning,
        )

    def model_registry(self) -> ModelRegistry:
        raw = (self.settings.model_library_path or "").strip()
        library = Path(raw).expanduser() if raw else default_library_dir()
        return ModelRegistry(library)

    def runpod_client(self) -> RunPodClient:
        key = self.secrets.get("runpod_api_key")
        return RunPodClient(key)

    def confirm_from_worker(self, title: str, message: str) -> bool:
        return confirm_from_worker(self, title, message)

    # ------------------------------------------------- agent tool registry
    def agent_extra_tools(self):
        """Context + connector + training-control tools for the mentor agent."""
        def get_training_status(_args):
            status = self.training.status()
            summary = parse_log(self.training.tail())
            return {
                "ok": True,
                "running": status.running,
                "returncode": status.returncode,
                "command": status.command,
                "metrics": summary.last,
                "best": summary.best,
                "trend": summary.trend,
                "anomalies": summary.anomalies,
                "epoch": summary.epoch_current,
                "epochs_total": summary.epochs_total,
                "progress": summary.progress_ratio,
            }

        def read_training_log(args):
            try:
                max_bytes = max(500, min(int(args.get("max_bytes", 8000)), 60000))
            except (TypeError, ValueError):
                max_bytes = 8000
            return {"ok": True, "output": self.training.tail(max_bytes)}

        def get_run_history(args):
            try:
                limit = max(1, min(int(args.get("limit", 5)), 20))
            except (TypeError, ValueError):
                limit = 5
            runs = [
                {
                    "command": record.command,
                    "status": record.status_ru,
                    "started": record.started_at,
                    "metrics": record.metrics_last,
                    "anomalies": record.anomalies,
                    "score": record.analysis_score,
                }
                for record in self.runs.list(limit)
            ]
            return {"ok": True, "runs": runs}

        def start_training(args):
            command = str(args.get("command") or "").strip() or self.settings.training_command
            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": "Рабочая папка не выбрана."}
            try:
                log_path = self.training.start(command, root)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            record = self.runs.start(command, str(root), log_path)
            self.activity.log("training", f"Агент запустил обучение: {command}",
                              run_id=record.id)
            return {"ok": True, "log_path": log_path, "run_id": record.id}

        def stop_training(_args):
            if not self.training.status().running:
                return {"ok": True, "note": "Обучение не запущено."}
            try:
                self.training.stop()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log("training", "Агент остановил обучение")
            return {"ok": True}

        def diagnostics(_args):
            try:
                results = run_diagnostics(self.settings, self.secrets)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "summary": diagnostics_summary(results),
                    "report": diagnostics_text(results), "checks": results}

        def get_model_info(_args):
            from .training import read_control as read_hot_control

            root = self.workspace_root()
            entry = None
            try:
                for candidate in self.model_registry().load():
                    if candidate.id == self.settings.active_model_id:
                        entry = candidate
                        break
            except Exception:  # noqa: BLE001
                entry = None
            config_data: object = None
            if root is not None:
                config_file = Path(root) / "config.json"
                if config_file.is_file():
                    try:
                        config_data = json.loads(
                            config_file.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        config_data = config_file.read_text(
                            encoding="utf-8", errors="replace")[:1500]
            status = self.training.status()
            summary = parse_log(self.training.tail())
            return {
                "ok": True,
                "model": None if entry is None else {
                    "id": entry.id, "name": entry.name, "kind": entry.kind,
                    "location": entry.location, "model_id": entry.model_id,
                    "notes": entry.notes,
                },
                "project_config": config_data,
                "training_control": (read_hot_control(root)
                                     if root is not None else {}),
                "training": {"running": status.running,
                             "command": status.command,
                             "returncode": status.returncode},
                "metrics": {"last": summary.last, "best": summary.best,
                            "trend": summary.trend,
                            "anomalies": summary.anomalies,
                            "epoch": summary.epoch_current,
                            "epochs_total": summary.epochs_total},
            }

        def list_model_catalog(_args):
            try:
                entries = self.model_registry().load()
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "models": [
                {"id": entry.id, "name": entry.name, "kind": entry.kind,
                 "location": entry.location, "model_id": entry.model_id,
                 "notes": entry.notes}
                for entry in entries
            ]}

        def get_metrics_history(args):
            raw_keys = args.get("keys") or []
            keys = [str(key) for key in raw_keys][:8] if isinstance(
                raw_keys, list) else []
            try:
                limit = max(1, min(int(args.get("limit", 200)), 1000))
            except (TypeError, ValueError):
                limit = 200
            summary = parse_log(self.training.tail())
            wanted = keys or sorted({
                key for point in summary.points for key in point.values})
            series = {
                key: summary.series(key)[-limit:] for key in wanted
            }
            return {"ok": True, "series": series,
                    "epochs": [point.epoch for point in summary.points[-limit:]],
                    "best": summary.best, "trend": summary.trend,
                    "anomalies": summary.anomalies}

        def get_training_control(_args):
            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": "Рабочая папка не выбрана."}
            from .training import CONTROL_KEYS, read_control as read_hot_control

            return {"ok": True, "control": read_hot_control(root),
                    "keys": list(CONTROL_KEYS)}

        def set_training_control(args):
            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": "Рабочая папка не выбрана."}
            from .training import write_control

            params = {key: value for key, value in (args or {}).items()
                      if value is not None}
            try:
                current = write_control(root, params)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log(
                "training",
                "Агент скорректировал обучение: "
                + ", ".join(f"{key}={value}" for key, value in params.items()),
            )
            return {"ok": True, "control": current,
                    "note": "Изменения применяются со следующей эпохи обучения."}

        def set_plan(args):
            steps = args.get("steps") or []
            if not isinstance(steps, list) or not steps:
                return {"ok": False, "error": "План должен содержать шаги."}
            clean = [str(step).strip()[:200] for step in steps if str(step).strip()][:12]
            self.agent_plan = clean
            self.activity.log("plan", "План агента:\n- " + "\n- ".join(clean))
            return {"ok": True, "steps": clean}

        def spawn_subagent(args):
            if not self.settings.agent_subagents:
                return {"ok": False, "error": "Подагенты отключены в настройках агента."}
            goal = str(args.get("goal") or "").strip()
            if not goal:
                return {"ok": False, "error": "Укажите подзадачу (goal)."}
            try:
                steps = max(2, min(int(args.get("max_steps", 6)), 10))
            except (TypeError, ValueError):
                steps = 6
            try:
                from .agent import MentorAgent, MODEL_TOOLS_SCHEMAS as _MTS
                from .agent import TRAINING_CONTEXT_TOOL_SCHEMAS as _TCS
                from .tools import WorkspaceTools

                workspace = None
                root = self.workspace_root()
                if root is not None:
                    workspace = WorkspaceTools(root)
                mentor = self.mentor_client()
                subagent = MentorAgent(
                    mentor, workspace,
                    max_steps=steps,
                    extra_tools={
                        "get_training_status": get_training_status,
                        "read_training_log": read_training_log,
                        "get_run_history": get_run_history,
                        "get_model_info": get_model_info,
                        "list_model_catalog": list_model_catalog,
                        "get_metrics_history": get_metrics_history,
                        "get_training_control": get_training_control,
                    },
                    extra_schemas=_TCS + _MTS,
                    extra_mutations={"set_training_control", "set_plan"},
                    autonomy="assist",
                )
                reply = subagent.run_goal(goal, max_tokens=900, verify=False)
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"ok": True, "report": reply.text[:4000], "steps": steps}

        handlers = {
            "get_training_status": get_training_status,
            "read_training_log": read_training_log,
            "get_run_history": get_run_history,
            "start_training": start_training,
            "stop_training": stop_training,
            "run_diagnostics": diagnostics,
            "get_model_info": get_model_info,
            "list_model_catalog": list_model_catalog,
            "get_metrics_history": get_metrics_history,
            "get_training_control": get_training_control,
            "set_training_control": set_training_control,
            "set_plan": set_plan,
            "spawn_subagent": spawn_subagent,
        }
        schemas = list(TRAINING_CONTEXT_TOOL_SCHEMAS) + list(MODEL_TOOLS_SCHEMAS) + [
            {"type": "function", "function": {
                "name": "start_training",
                "description": "Запустить обучение в рабочей папке (командой из настроек "
                               "или из аргумента command).",
                "parameters": {"type": "object", "properties": {
                    "command": {"type": "string"}}, "required": []}}},
            {"type": "function", "function": {
                "name": "stop_training",
                "description": "Остановить текущее обучение.",
                "parameters": {"type": "object", "properties": {}, "required": []}}},
            {"type": "function", "function": {
                "name": "run_diagnostics",
                "description": "Проверка окружения: Python, хранилище ключей, SSH, Git, "
                               "рабочая папка, диск, настройки наставника.",
                "parameters": {"type": "object", "properties": {}, "required": []}}},
        ]
        mutations = {"start_training", "stop_training", "set_training_control"}

        try:
            manager = ConnectorManager(self.secrets,
                                       gmail_from=self.settings.gmail_from)
            conn_handlers, conn_schemas, conn_mutations = manager.agent_tools()
            handlers.update(conn_handlers)
            schemas.extend(conn_schemas)
            mutations |= set(conn_mutations)
        except Exception:  # noqa: BLE001 - connectors must not break the agent
            pass

        try:
            srv_handlers, srv_schemas, srv_mutations = \
                self.server_manager().agent_tools()
            handlers.update(srv_handlers)
            schemas.extend(srv_schemas)
            mutations |= set(srv_mutations)
        except Exception:  # noqa: BLE001 - servers must not break the agent
            pass

        return handlers, schemas, frozenset(mutations)

    # ---------------------------------------------------------- assessment
    def assessment_context(self) -> str:
        lines: list[str] = []
        entry = None
        try:
            for candidate in self.model_registry().load():
                if candidate.id == self.settings.active_model_id:
                    entry = candidate
                    break
        except Exception:
            entry = None
        if entry is not None:
            lines += [
                f"Модель: {entry.name} ({entry.kind})",
                f"Путь/URI: {entry.location}",
                f"API model id: {entry.model_id or '—'}",
                f"Заметки: {entry.notes or '—'}",
                "",
            ]
        else:
            lines += ["Модель не выбрана в каталоге.", ""]

        status = self.training.status()
        summary = parse_log(self.training.tail())
        lines += [
            f"Обучение: {'выполняется' if status.running else 'остановлено'}",
            f"Команда: {status.command or '—'}",
            f"Код возврата: {status.returncode}",
            f"Метрики: {metrics_brief(summary)}",
        ]
        if summary.anomalies:
            lines.append("Аномалии: " + "; ".join(summary.anomalies))
        recent_runs = self.runs.list(5)
        if recent_runs:
            lines.append("")
            lines.append("Последние запуски:")
            for record in recent_runs:
                lines.append(
                    f"- {record.command} → {record.status_ru}; "
                    f"метрики: {record.metrics_last or '—'}"
                )
        tail = self.training.tail(6000)
        if tail.strip():
            lines += ["", "Хвост лога:", "```", tail, "```"]
        return "\n".join(lines)

    def assessment_prompt(self) -> str:
        return REPORT_PROMPT_TEMPLATE.format(context=self.assessment_context())

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
