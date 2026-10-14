"""Tkinter IDE shell: sidebar, center workspace, bottom terminal, right chat."""
from __future__ import annotations

import json
import queue
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

from . import ui_common
from .activity import ActivityLog
from .agent import MODEL_TOOLS_SCHEMAS, TRAINING_CONTEXT_TOOL_SCHEMAS
from .cloud_gpu import RunPodClient
from .config import AppSettings, SecretStore, app_data_dir
from .i18n import set_language, t
from .connectors import ConnectorManager
from .roles import can
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
        set_language(self.settings.ui_language)
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
        self.agent_tasks: list[dict] = []
        from .watchdog import TrainingWatchdog

        self.watchdog = TrainingWatchdog()
        self._watchdog_tail: tuple[int, float] = (0, 0.0)
        self._watchdog_started = False
        from .plugins import PluginManager

        self.plugins = PluginManager(app_data_dir() / "plugins")
        self._plugin_list = self.plugins.load_all()
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
            (t("nav.development"), [
                ("editor", t("nav.editor")),
                ("workspace", t("nav.workspace")),
                ("search", t("nav.search")),
            ]),
            (t("nav.library"), [
                ("models", t("nav.models")),
                ("datasets", t("nav.datasets")),
                ("model", t("nav.model")),
            ]),
            (t("nav.experiments"), [
                ("playground", t("nav.playground")),
                ("training", t("nav.training")),
                ("gpu", t("nav.gpu")),
            ]),
            (t("nav.system"), [
                ("servers", t("nav.servers")),
                ("connectors", t("nav.connectors")),
                ("settings", t("nav.settings")),
            ]),
        ]
        for group_title, items in nav_groups:
            tk.Label(sidebar, text=group_title, bg=C["sidebar"], fg="#5b6b85",
                     font=F_NAV_SMALL, anchor="w", padx=16).pack(fill="x",
                                                                 pady=(10, 2))
            for key, label in items:
                self._make_nav_item(sidebar, key, label)

        tk.Label(sidebar, text=t("brand.version"), bg=C["sidebar"],
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
        self._start_watchdog()
        self.set_status(t("status.ready"))

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

    # ------------------------------------------------------------- layouts
    def current_layout(self):
        """Snapshot the current arrangement as a LayoutState."""
        from .layouts import LayoutState

        geometry = ""
        try:
            geometry = str(self.geometry() or "")
        except Exception:  # noqa: BLE001
            geometry = ""
        return LayoutState(
            page=self._current_page or "editor",
            bottom_visible=bool(getattr(self, "_bottom_visible", True)),
            bottom_view=self._bottom_view or "terminal",
            geometry=geometry)

    def apply_layout(self, state):
        """Restore an arrangement saved earlier or a named preset."""
        try:
            self.show_page(state.page)
            if bool(state.bottom_visible) != bool(
                    getattr(self, "_bottom_visible", True)):
                self.toggle_bottom()
            if state.bottom_visible:
                self.show_bottom(state.bottom_view or "terminal")
            if state.geometry:
                self.geometry(state.geometry)
        except Exception:  # noqa: BLE001 - layout must not break startup
            return
        self.settings.active_layout = "custom"
        self.save_settings()

    def _bind_shortcuts(self):
        from .hotkeys import resolve_hotkeys

        actions = {
            "page.editor": lambda _e: self.show_page("editor"),
            "page.workspace": lambda _e: self.show_page("workspace"),
            "page.models": lambda _e: self.show_page("models"),
            "page.datasets": lambda _e: self.show_page("datasets"),
            "page.model": lambda _e: self.show_page("model"),
            "page.playground": lambda _e: self.show_page("playground"),
            "page.training": lambda _e: self.show_page("training"),
            "page.gpu": lambda _e: self.show_page("gpu"),
            "page.servers": lambda _e: self.show_page("servers"),
            "page.settings": lambda _e: self.show_page("settings"),
            "page.chat": lambda _e: self.show_page("chat"),
            "page.search": lambda _e: self.show_page("search"),
            "panel.toggle": lambda _e: self.toggle_bottom(),
            "panel.problems": lambda _e: self.show_bottom("problems"),
            "panel.git": lambda _e: self.show_bottom("git"),
            "palette.files": lambda _e: self.open_command_palette("files"),
            "palette.commands": lambda _e: self.open_command_palette("commands"),
            "app.refresh": lambda _e: self.refresh_current(),
            "app.help": lambda _e: self.show_shortcuts_help(),
        }
        bindings = resolve_hotkeys(self.settings.hotkeys)
        for action_id, handler in actions.items():
            sequence = bindings.get(action_id)
            if sequence:
                self.bind_all(sequence, handler)

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

    def catalog_entry(self, model_id: str):
        """Find a model catalog entry by id or name (None if absent)."""
        try:
            entries = self.model_registry().load()
        except Exception:  # noqa: BLE001
            return None
        key = str(model_id or "").strip().lower()
        if not key:
            return None
        for entry in entries:
            if entry.id == model_id or entry.name.lower() == key \
                    or entry.model_id.lower() == key:
                return entry
        return None

    def build_report_context(self):
        """Assemble everything known about the current training into a report."""
        from .evaluation import build_eval_report
        from .report_export import ReportContext
        from .watchdog import detect_issues

        summary = parse_log(self.training.tail())
        context = ReportContext(title="Отчёт по обучению — AlterEgo Training Hub")
        entry = None
        for candidate in self.model_registry().load():
            if candidate.id == self.settings.active_model_id:
                entry = candidate
                break
        context.model_info = {
            "Модель": entry.name if entry else self.settings.active_model_id or "—",
            "Тип": entry.kind if entry else "—",
            "Расположение": entry.location if entry else "—",
            "Команда обучения": self.settings.training_command or "—",
        }
        context.metrics_lines = [
            f"- {key}: {value:g}" for key, value in sorted(summary.last.items())]
        if summary.trend:
            context.metrics_lines.append(
                "- тренды: " + ", ".join(f"{k}={v}"
                                         for k, v in summary.trend.items()))
        context.eval_lines = build_eval_report(self.training.tail()).lines()
        status = self.training.status()
        context.watchdog_lines = [
            issue.line() for issue in detect_issues(
                summary, running=status.running)]
        context.plan_tasks = list(self.agent_tasks or
                                  [{"title": t, "status": "pending"}
                                   for t in self.agent_plan])
        context.activity_lines = [
            f"{item.kind}: {item.summary[:120]}"
            for item in self.activity.recent(15)]
        report = self.reports.latest()
        if report is not None and not report.is_empty():
            if report.score is not None:
                context.assessment_lines.append(f"Оценка: {report.score:g}/10")
            for label, items in (("Сильные стороны", report.strengths),
                                 ("Слабые стороны", report.weaknesses),
                                 ("Риски", report.risks),
                                 ("Рекомендации", report.recommendations)):
                for item in items:
                    context.assessment_lines.append(f"- ({label}) {item}")
            if report.reasoning:
                context.assessment_lines.append(report.reasoning[:1500])
        return context

    # ----------------------------------------------------------- watchdog
    def _start_watchdog(self):
        """Poll training health in the background; log fresh issues once."""
        if self._watchdog_started:
            return
        self._watchdog_started = True
        try:
            self.after(15_000, self._watchdog_tick)
        except Exception:  # noqa: BLE001 - no display server (tests)
            pass

    def _watchdog_tick(self):
        try:
            status = self.training.status()
            if status.running:
                tail = self.training.tail()
                now = time.time()
                last_len, last_time = self._watchdog_tail
                quiet = 0.0
                if len(tail) == last_len and last_time:
                    quiet = now - last_time
                self._watchdog_tail = (len(tail), now if len(tail) != last_len
                                       else last_time or now)
                from .metrics import parse_log
                from .watchdog import DEFAULT_QUIET_SECONDS

                summary = parse_log(tail)
                report = self.watchdog.evaluate(
                    summary, running=True,
                    quiet_seconds=quiet if quiet >= DEFAULT_QUIET_SECONDS else 0.0)
                for issue in report.issues:
                    self.activity.log("watchdog", issue.line(),
                                      ok=issue.severity == "info")
                if any(issue.severity == "crit" for issue in report.issues):
                    self.set_status("⚠ Watchdog: критическая проблема обучения")
            else:
                self._watchdog_tail = (0, 0.0)
                self.watchdog.reset()
        except Exception:  # noqa: BLE001 - watchdog must never crash the app
            pass
        try:
            self.after(15_000, self._watchdog_tick)
        except Exception:  # noqa: BLE001
            pass

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
            self.watchdog.reset()
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
            self.agent_tasks = [{"title": step, "status": "pending"} for step in clean]
            self.activity.log("plan", "План агента:\n- " + "\n- ".join(clean))
            return {"ok": True, "steps": clean}

        def update_plan(args):
            raw_steps = args.get("steps") or []
            if not isinstance(raw_steps, list) or not raw_steps:
                return {"ok": False, "error": "План должен содержать шаги."}
            allowed = {"pending", "in_progress", "done", "failed"}
            tasks: list[dict] = []
            for item in raw_steps[:12]:
                if isinstance(item, dict):
                    title = str(item.get("title") or "").strip()[:200]
                    status = str(item.get("status") or "pending")
                else:
                    title, status = str(item).strip()[:200], "pending"
                if title:
                    tasks.append({"title": title,
                                  "status": status if status in allowed
                                  else "pending"})
            if not tasks:
                return {"ok": False, "error": "План должен содержать шаги."}
            self.agent_tasks = tasks
            self.agent_plan = [task["title"] for task in tasks]
            marks = {"done": "✓", "failed": "✗", "in_progress": "▶", "pending": "○"}
            self.activity.log("plan", "План агента:\n" + "\n".join(
                f"{marks.get(task['status'], '○')} {task['title']}"
                for task in tasks))
            chat_panel = getattr(self, "chat_panel", None)
            handler = getattr(chat_panel, "on_agent_event", None)
            if callable(handler):
                handler("plan", {"tasks": tasks})
            return {"ok": True, "tasks": tasks}

        def get_eval_report(_args):
            from .evaluation import build_eval_report

            report = build_eval_report(self.training.tail())
            return {"ok": True, "points": len(report.points),
                    "best_epoch": report.best_epoch,
                    "best_val_loss": report.best_val_loss,
                    "overfitting": report.overfitting,
                    "lines": report.lines()}

        def suggest_training_fixes(_args):
            from .hparam_tuning import suggest_fixes
            from .training import read_control as read_hot_control

            root = self.workspace_root()
            control = read_hot_control(root) if root is not None else {}
            summary = parse_log(self.training.tail())
            suggestions = suggest_fixes(summary, control)
            return {"ok": True,
                    "control": control,
                    "suggestions": [
                        {"param": s.param, "value": s.value,
                         "reason": s.reason, "confidence": s.confidence}
                        for s in suggestions],
                    "lines": [s.line() for s in suggestions],
                    "note": "Применяй выбранные параметры через set_training_control."}

        def compare_runs(args):
            from .compare import compare_runs as _compare, overlay_series

            key = str(args.get("key") or "loss")
            records = [record for record in self.runs.list(10)
                       if record.log_path and Path(record.log_path).is_file()]
            if len(records) < 2:
                return {"ok": False,
                        "error": "Нужны два завершённых запуска с логами."}
            first, second = records[0], records[1]
            summary_a = parse_log(Path(first.log_path).read_text(
                encoding="utf-8", errors="replace"))
            summary_b = parse_log(Path(second.log_path).read_text(
                encoding="utf-8", errors="replace"))
            report = _compare(summary_a, summary_b,
                              label_a="Запуск 1", label_b="Запуск 2")
            return {"ok": True,
                    "run_a": first.command, "run_b": second.command,
                    "series": overlay_series(key, summary_a, summary_b),
                    "winner": report.winner,
                    "lines": report.lines()}

        def prepare_dataset(args):
            from .datasets import DatasetError, filter_rows, read_rows, \
                split_rows, write_rows

            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": "Рабочая папка не выбрана."}
            rel = str(args.get("path") or "")
            source = Path(root) / rel
            if not source.is_file():
                return {"ok": False, "error": f"Файл не найден: {rel}"}
            fmt = source.suffix.lstrip(".").lower()
            if fmt not in {"jsonl", "json", "csv", "tsv", "txt"}:
                return {"ok": False, "error": f"Неподдерживаемый формат: {fmt}"}
            try:
                rows = read_rows(source, fmt)
                rows = filter_rows(
                    rows, field=str(args.get("field") or "text"),
                    contains=str(args.get("contains") or ""),
                    excludes=str(args.get("excludes") or ""),
                    min_chars=int(args.get("min_chars") or 0),
                    max_chars=int(args.get("max_chars") or 0))
                parts = split_rows(
                    rows,
                    train=float(args.get("train_ratio", 0.8)),
                    val=float(args.get("val_ratio", 0.1)),
                    test=float(args.get("test_ratio", 0.1)),
                    seed=int(args.get("seed", 42)))
            except (DatasetError, TypeError, ValueError) as exc:
                return {"ok": False, "error": str(exc)}
            stem = source.stem
            written = {}
            for part, part_rows in parts.items():
                target = source.with_name(f"{stem}.{part}.{fmt}")
                write_rows(target, part_rows, fmt)
                written[part] = {"path": str(target.relative_to(root)),
                                 "rows": len(part_rows)}
            self.activity.log("dataset",
                              "Агент разбил датасет: "
                              + ", ".join(f"{k}={v['rows']}" for k, v in written.items()))
            return {"ok": True, "splits": written, "filtered_rows": len(rows)}

        def _endpoint_client(entry):
            from .playground import PlaygroundClient

            try:
                key = self.secrets.get("mentor_api_key")
            except RuntimeError:
                key = ""
            return PlaygroundClient(entry.base_url, entry.model_id, key)

        def export_model(args):
            from .exporting import EXPORT_FORMATS, ExportRequest, run_export

            entry = self.catalog_entry(str(args.get("model_id") or ""))
            source = str(args.get("source") or (entry.location if entry else ""))
            if entry and entry.kind == "cloud":
                return {"ok": False,
                        "error": "Облачную модель нельзя экспортировать локально."}
            fmt = str(args.get("format") or "gguf").lower()
            library = self.model_registry().library_dir
            request = ExportRequest(
                source=source, fmt=fmt,
                output_dir=str(Path(library) / "exports"),
                out_type=str(args.get("out_type") or "f16"))
            result = run_export(request)
            self.activity.log(
                "model",
                f"Экспорт {fmt}: " + ("успешно" if result.ok else result.error))
            return {"ok": result.ok, "format": fmt, "command": result.command,
                    "output_path": result.output_path,
                    "size_bytes": result.size_bytes,
                    "checks": result.checks, "error": result.error,
                    "hint": EXPORT_FORMATS.get(fmt, {}).get("tool_hint", "")}

        def quantize_model(args):
            from .quantize import QUANT_RECIPES, recipe_info, run_quantize

            entry = self.catalog_entry(str(args.get("model_id") or ""))
            source = str(args.get("source") or (entry.location if entry else ""))
            quant_type = str(args.get("quant_type") or "q4_k_m").lower()
            try:
                recipe = recipe_info(quant_type)
            except Exception as exc:
                return {"ok": False, "error": str(exc),
                        "types": sorted(QUANT_RECIPES)}
            library = self.model_registry().library_dir
            stem = Path(source).stem or "model"
            suffix = ".gguf" if recipe.family == "gguf" else ".onnx"
            destination = str(Path(library) / "exports" /
                              f"{stem}.{quant_type}{suffix}")
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            result = run_quantize(source, destination, quant_type)
            self.activity.log(
                "model",
                f"Квантизация {quant_type}: "
                + ("успешно" if result.ok else result.error))
            return {"ok": result.ok, "recipe": quant_type,
                    "command": result.command, "output_path": result.output_path,
                    "checks": result.checks, "error": result.error}

        def benchmark_model(args):
            from .bench import BenchResult, BenchStore, format_bench_table, \
                rank_benchmarks, run_benchmark

            entry = self.catalog_entry(str(args.get("model_id") or ""))
            command = str(args.get("command") or "").strip()
            try:
                iterations = max(1, min(int(args.get("iterations") or 3), 10))
            except (TypeError, ValueError):
                iterations = 3
            if command:
                result = run_benchmark("команда", command, iterations=iterations)
            elif entry and entry.base_url:
                client = _endpoint_client(entry)
                durations: list[int] = []
                tokens_chars = 0
                error = ""
                for _ in range(iterations):
                    try:
                        probe = client.generate("Скажи «ок».", max_tokens=8,
                                                temperature=0.0)
                        if probe.error:
                            error = probe.error
                            break
                        durations.append(probe.latency_ms)
                        tokens_chars = max(tokens_chars, len(probe.output))
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        break
                if error:
                    result = BenchResult(model=entry.name, command="endpoint probe",
                                         error=error)
                else:
                    mean = int(sum(durations) / max(1, len(durations)))
                    result = BenchResult(model=entry.name, command="endpoint probe",
                                         iterations=len(durations),
                                         duration_ms=mean,
                                         output_chars=tokens_chars)
            else:
                return {"ok": False,
                        "error": "Укажите model_id (модель с endpoint) или command."}
            library = self.model_registry().library_dir
            BenchStore(library).add(result)
            self.activity.log("bench", result.line())
            return {"ok": result.ok(), "line": result.line(),
                    "table": format_bench_table([result]),
                    "rank": rank_benchmarks([result]),
                    "error": result.error}

        def run_prompt_suite(args):
            from .prompt_suite import default_suite, format_suite_report, \
                load_suite, run_suite

            entry = self.catalog_entry(str(args.get("model_id") or ""))
            if entry and entry.base_url:
                client = _endpoint_client(entry)
                model_name = entry.name
            else:
                settings = self.settings
                if not (settings.mentor_base_url and settings.mentor_model):
                    return {"ok": False,
                            "error": "Нужна модель с endpoint (model_id) "
                                     "или настроенный провайдер."}
                client = _endpoint_client(type("E", (), {
                    "base_url": settings.mentor_base_url,
                    "model_id": settings.mentor_model,
                    "name": settings.mentor_model})())
                model_name = settings.mentor_model
            suite_rel = str(args.get("suite_path") or "").strip()
            try:
                if suite_rel and suite_rel.lower() != "default":
                    root = self.workspace_root()
                    if root is None:
                        return {"ok": False,
                                "error": "Рабочая папка не выбрана."}
                    cases = load_suite(Path(root) / suite_rel)
                else:
                    cases = default_suite()
                try:
                    max_tokens = max(32, min(int(args.get("max_tokens") or 400), 2000))
                except (TypeError, ValueError):
                    max_tokens = 400
                result = run_suite(client, cases, model=model_name,
                                   max_tokens=max_tokens)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log("suite", f"Промпт-набор: {result.passed}/{result.total}")
            return {"ok": True, "model": model_name,
                    "passed": result.passed, "total": result.total,
                    "mean_latency_ms": result.mean_latency_ms,
                    "report": format_suite_report(result)}

        def export_report(args):
            from .report_export import save_report

            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": "Рабочая папка не выбрана."}
            rel = str(args.get("path") or "reports/report")
            fmt = str(args.get("format") or "md").lower()
            try:
                exported = save_report(Path(root) / rel, self.build_report_context(),
                                       fmt=fmt)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log("report", f"Отчёт сохранён: {exported.path}")
            return {"ok": True, "path": exported.path, "format": exported.fmt,
                    "note": exported.note}

        def list_cloud_jobs(_args):
            from .cloud_queue import CloudJobQueue

            queue = CloudJobQueue(self.model_registry().library_dir)
            return {"ok": True,
                    "jobs": [{"id": job.id, "name": job.name,
                              "command": job.command, "status": job.status,
                              "pod_id": job.pod_id, "error": job.error,
                              "line": job.line()}
                             for job in queue.list()],
                    "lines": [job.line() for job in queue.list()]}

        def submit_cloud_job(args):
            from .cloud_queue import CloudJob, CloudJobQueue

            try:
                key = self.secrets.get("runpod_api_key")
            except RuntimeError as exc:
                return {"ok": False, "error": str(exc)}
            try:
                job = CloudJob(
                    name=str(args.get("name") or "задание"),
                    command=str(args.get("command") or ""),
                    image=str(args.get("image") or "python:3.11-slim"),
                    gpu_type=str(args.get("gpu_type") or ""))
                queue = CloudJobQueue(self.model_registry().library_dir)
                queue.add(job)
                client = RunPodClient(key)
                queued = queue.submit(job.id, client)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log("cloud", f"Облачное задание: {queued.line()}")
            return {"ok": queued.status == "submitted", "job": queued.line(),
                    "status": queued.status, "pod_id": queued.pod_id,
                    "error": queued.error}

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
            "update_plan": update_plan,
            "spawn_subagent": spawn_subagent,
            "get_eval_report": get_eval_report,
            "suggest_training_fixes": suggest_training_fixes,
            "compare_runs": compare_runs,
            "prepare_dataset": prepare_dataset,
            "export_model": export_model,
            "quantize_model": quantize_model,
            "benchmark_model": benchmark_model,
            "run_prompt_suite": run_prompt_suite,
            "export_report": export_report,
            "list_cloud_jobs": list_cloud_jobs,
            "submit_cloud_job": submit_cloud_job,
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
        mutations = {"start_training", "stop_training", "set_training_control",
                     "prepare_dataset", "export_model", "quantize_model",
                     "benchmark_model", "run_prompt_suite", "export_report",
                     "submit_cloud_job"}

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

        # Third-party plugin tools extend the agent without touching the core.
        plugin_list = getattr(self, "_plugin_list", None)
        if plugin_list is not None:
            handlers.update(self.plugins.tool_handlers(plugin_list))
            schemas.extend(self.plugins.tool_schemas(plugin_list))
            mutations |= self.plugins.tool_mutations(plugin_list)

        if not can(self.settings.access_role, "mutate"):
            # Guest role: every mutation is refused up-front (read-only agent).
            def _denied(_args):
                return {"ok": False,
                        "error": "Гостевой режим (роль «гость»): действие недоступно."}

            for name in sorted(mutations):
                handlers[name] = _denied

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
