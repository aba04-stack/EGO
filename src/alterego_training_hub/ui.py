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
from .connectors import ConnectorManager
from .diagnostics import diagnostics_summary, diagnostics_text, run_diagnostics
from .git_manager import GitRepositoryManager
from .i18n import set_language, t
from .logging_setup import install_excepthook, log_worker_error, setup_logging
from .mentor import ApiMentor, MentorError
from .metrics import brief as metrics_brief
from .metrics import parse_log
from .models_registry import ModelRegistry, default_library_dir
from .report import REPORT_PROMPT_TEMPLATE, ReportStore
from .roles import can
from .runs import RunStore
from .servers import ServerManager, ServerStore
from .training import TrainingRun
from .ui_common import F_NAV, F_NAV_SMALL, C, confirm_from_worker


class TrainingHubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        setup_logging()
        install_excepthook()
        self.title("EGO")
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
        self._budget_daemon_started = False
        from .plugins import PluginManager

        self.plugins = PluginManager(app_data_dir() / "plugins")
        self._plugin_list = self.plugins.load_all()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ego-hub")
        import threading as _threading

        self.closing_event = _threading.Event()  # кооперативная отмена фоновых задач
        self._closing = False
        self._nav_buttons: dict[str, tk.Label] = {}
        self._nav_accent: dict[str, tk.Frame] = {}
        self._nav_meta: dict[str, tuple[str, str]] = {}
        self._nav_badges: dict[str, str] = {}
        self._sidebar_compact = False
        self._sidebar_refresh_after: str | None = None
        self._tokens_today = 0
        self.pages: dict[str, tk.Frame] = {}

        ui_common.apply_theme(self)
        self._build_layout()
        self._poll_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ layout
    def _build_layout(self):
        self.status_bar = tk.Frame(self, bg=C["statusbar"],
                                   highlightbackground=C["border"],
                                   highlightthickness=1)
        self.status_bar.pack(side="bottom", fill="x")
        self.status_text = tk.StringVar(value=t('Готово'))
        tk.Label(self.status_bar, textvariable=self.status_text, bg=C["statusbar"],
                 fg=C["muted"], font=ui_common.F_SMALL, anchor="w",
                 padx=12).pack(side="left", fill="x", expand=True)
        self.workspace_badge = tk.StringVar(value=t('папка не выбрана'))
        _wb = tk.Label(self.status_bar, textvariable=self.workspace_badge,
                       bg=C["statusbar"],
                       fg=C["muted"], font=ui_common.F_SMALL, padx=12,
                       cursor="hand2")
        _wb.pack(side="right")
        _wb.bind("<Button-1>", lambda _e: self.show_page("workspace"))
        self.git_badge = tk.StringVar(value="")
        _gb = tk.Label(self.status_bar, textvariable=self.git_badge,
                       bg=C["statusbar"],
                       fg=C["muted"], font=ui_common.F_SMALL, padx=12,
                       cursor="hand2")
        _gb.pack(side="right")
        _gb.bind("<Button-1>", lambda _e: self.show_bottom("git"))
        self.model_badge = tk.StringVar(value="")
        _mb = tk.Label(self.status_bar, textvariable=self.model_badge,
                       bg=C["statusbar"], fg=C["muted"], font=ui_common.F_SMALL,
                       padx=12, cursor="hand2")
        _mb.pack(side="right")
        _mb.bind("<Button-1>", lambda _e: self.show_page("model"))
        self.tokens_badge = tk.StringVar(value="")
        tk.Label(self.status_bar, textvariable=self.tokens_badge,
                 bg=C["statusbar"], fg=C["muted"], font=ui_common.F_SMALL,
                 padx=12).pack(side="right")
        self.training_badge = tk.StringVar(value="")
        _tb = tk.Label(self.status_bar, textvariable=self.training_badge,
                       bg=C["statusbar"], fg=C["muted"], font=ui_common.F_SMALL,
                       padx=12, cursor="hand2")
        _tb.pack(side="right")
        _tb.bind("<Button-1>", lambda _e: self.show_page("training"))

        container = tk.Frame(self, bg=C["bg"])
        container.pack(fill="both", expand=True)
        self._container = container

        # ---- Sidebar (navigation, dockable to left/right) -------------
        sidebar = tk.Frame(container, bg=C["sidebar"], width=216)
        sidebar.pack_propagate(False)
        self._sidebar_frame = sidebar
        sidebar.bind(
            "<Configure>",
            lambda _event: self._schedule_sidebar_label_refresh(),
            add="+",
        )
        brand = tk.Frame(sidebar, bg=C["sidebar"])
        brand.pack(fill="x", pady=(18, 12), padx=16)
        tk.Label(brand, text="EGO", bg=C["sidebar"], fg="#ffffff",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(brand, text=t("brand.subtitle"), bg=C["sidebar"], fg=C["sidebar_fg"],
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Frame(brand, bg=C["accent"], height=2).pack(fill="x", pady=(10, 0))

        self._compact_btn = tk.Label(sidebar, text="«", bg=C["sidebar"],
                                     fg=C["sidebar_fg"], font=F_NAV,
                                     anchor="e", padx=16, cursor="hand2")
        self._compact_btn.pack(fill="x")
        self._compact_btn.bind("<Button-1>",
                               lambda _e: self.toggle_sidebar_compact())

        _quick_wrap = tk.Frame(sidebar, bg=C["sidebar"])
        _quick_wrap.pack(fill="x", padx=12, pady=(4, 8))
        _quick = tk.Label(_quick_wrap, text=t('⌕  Поиск и команды…'),
                          bg=C["sidebar_hover"], fg=C["sidebar_fg"], font=F_NAV_SMALL,
                          anchor="w", padx=10, pady=7, cursor="hand2")
        _quick.pack(fill="x")
        _quick.bind("<Button-1>",
                    lambda _e: self.open_command_palette("commands"))

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
            tk.Label(sidebar, text=group_title, bg=C["sidebar"],
                     fg=C["sidebar_muted"],
                     font=F_NAV_SMALL, anchor="w", padx=16).pack(fill="x",
                                                                 pady=(12, 2))
            for key, label in items:
                self._make_nav_item(sidebar, key, label)

        if bool(getattr(self.settings, "sidebar_compact", False)):
            self._sidebar_compact = True
            try:
                sidebar.configure(width=64)
            except Exception:
                pass

        from . import __version__

        tk.Label(sidebar,
                 text=t("brand.version").format(version=__version__),
                 bg=C["sidebar"],
                 fg=C["sidebar_muted"], font=F_NAV_SMALL).pack(side="bottom", pady=12)

        # ---- Chat panel (docked left/right) ---------------------------
        from .ui_chat import ChatPage

        self.chat_panel = ChatPage(container, self)
        self.chat_panel.configure(width=348)
        self.chat_panel.pack_propagate(False)

        # ---- Center: pages + terminal ---------------------------------
        center = tk.Frame(container, bg=C["bg"])
        self._center = center
        self._pack_docks()
        self._make_dock_grip(self._sidebar_frame, "sidebar")
        self._make_dock_grip(self.chat_panel, "chat")
        self.pages_host = tk.Frame(center, bg=C["bg"])
        self.pages_host.pack(fill="both", expand=True)

        from .ui_connectors import ConnectorsPage
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
        try:
            dock_height = int(self.settings.bottom_height or 156)
        except (TypeError, ValueError):
            dock_height = 156
        self.bottom.configure(height=max(80, min(800, dock_height)))
        self.bottom.pack_propagate(False)
        bottom_bar = tk.Frame(self.bottom, bg=C["panel"])
        bottom_bar.pack(fill="x")
        self._make_height_grip(self.bottom)
        self._bottom_view = "terminal"
        self._bottom_visible = True
        self.terminal_tab = tk.Label(bottom_bar, text=t('Терминал'), bg=C["panel"],
                                     fg=C["accent"], font=F_NAV_SMALL, padx=14,
                                     pady=8, cursor="hand2")
        self.terminal_tab.pack(side="left")
        self.terminal_tab.bind("<Button-1>",
                               lambda _e: self.show_bottom("terminal"))
        self.problems_tab = tk.Label(bottom_bar, text=t('Проблемы'), bg=C["panel"],
                                     fg=C["muted"], font=F_NAV_SMALL, padx=14,
                                     pady=8, cursor="hand2")
        self.problems_tab.pack(side="left")
        self.problems_tab.bind("<Button-1>",
                               lambda _e: self.show_bottom("problems"))
        self.git_tab = tk.Label(bottom_bar, text=t('Git'), bg=C["panel"],
                                fg=C["muted"], font=F_NAV_SMALL, padx=14,
                                pady=8, cursor="hand2")
        self.git_tab.pack(side="left")
        self.git_tab.bind("<Button-1>",
                          lambda _e: self.show_bottom("git"))
        tk.Label(bottom_bar, text=t('Ctrl+J — свернуть панель'), bg=C["panel"],
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
        self._start_budget_daemon()
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

    # ------------------------------------------------- panel docking (dnd)
    def _pack_docks(self):
        """Pack sidebar/center/chat according to the saved dock sides."""
        for widget in (self._sidebar_frame, self.chat_panel, self._center):
            widget.pack_forget()
        sidebar_side = str(getattr(self.settings, "sidebar_side", "left")
                           or "left")
        chat_side = str(getattr(self.settings, "chat_side", "right") or "right")
        pairs = [("sidebar", self._sidebar_frame, sidebar_side),
                 ("chat", self.chat_panel, chat_side)]
        for _name, widget, side in pairs:
            if side == "left":
                widget.pack(side="left", fill="y")
        self._center.pack(side="left", fill="both", expand=True)
        for _name, widget, side in reversed(pairs):
            if side == "right":
                widget.pack(side="right", fill="y")

    def _make_dock_grip(self, panel, source: str):
        """Thin draggable strip on top of a dockable panel."""
        grip = tk.Frame(panel, bg=C["panel_alt"], height=6, cursor="fleur")
        children = panel.winfo_children() or []
        if children:
            grip.pack(side="top", fill="x", before=children[0])
        else:
            grip.pack(side="top", fill="x")

        def on_release(event):
            from .layouts import edge_drop

            width = self.winfo_width()
            x = event.x_root - self.winfo_rootx()
            side = edge_drop(x, width)
            if side:
                self._dock_panel(source, side)

        grip.bind("<ButtonRelease-1>", on_release)
        return grip

    def _make_height_grip(self, panel):
        """Drag the strip on the bottom panel to change its height."""
        grip = tk.Frame(panel, bg=C["panel_alt"], height=4, cursor="sb_v_double_arrow")
        children = panel.winfo_children() or []
        if children:
            grip.pack(side="top", fill="x", before=children[0])
        else:
            grip.pack(side="top", fill="x")
        state = {"start_y": 0, "start_h": 210}

        def on_press(event):
            state["start_y"] = event.y_root
            try:
                state["start_h"] = int(panel.winfo_height() or 210)
            except (TypeError, ValueError):
                state["start_h"] = 210

        def on_drag(event):
            height = state["start_h"] + (state["start_y"] - event.y_root)
            panel.configure(height=max(80, min(800, int(height))))

        def on_release(_event):
            try:
                self.settings.bottom_height = max(
                    80, min(800, int(panel.winfo_height() or 210)))
            except (TypeError, ValueError):
                self.settings.bottom_height = 210
            self.save_settings()

        grip.bind("<Button-1>", on_press)
        grip.bind("<B1-Motion>", on_drag)
        grip.bind("<ButtonRelease-1>", on_release)
        return grip

    def _dock_panel(self, source: str, side: str) -> None:
        """Move sidebar/chat to a window edge and persist the arrangement."""
        side = str(side or "").strip().lower()
        if side not in {"left", "right"}:
            return
        if source == "sidebar":
            self.settings.sidebar_side = side
        elif source == "chat":
            self.settings.chat_side = side
        else:
            return
        self._pack_docks()
        self.save_settings()
        self.set_status(t("Применена раскладка «{v1}».").format(
            v1=f"{source}={side}"))

    # -------------------------------------------------------- live language
    def apply_language(self, lang: str) -> None:
        """Switch the interface language live — rebuild UI in place.

        Editor tabs (with unsaved text) and the chat session survive the
        rebuild; everything else is re-created from scratch in the new
        language.
        """
        editor = self.pages.get("editor")
        editor_snap = None
        if editor is not None and hasattr(editor, "snapshot"):
            try:
                editor_snap = editor.snapshot()
            except Exception:
                editor_snap = None
        chat = getattr(self, "chat_panel", None)
        chat_session = getattr(chat, "session", None)
        chat_cache = getattr(chat, "_sessions_cache", None)
        keep_page = self._current_page or "editor"
        keep_bottom = self._bottom_view or "terminal"

        set_language(lang)
        self.settings.ui_language = lang
        self.save_settings()

        for child in (self.winfo_children() or []):
            child.destroy()
        self._nav_buttons = {}
        self._nav_accent = {}
        self.pages = {}
        ui_common.apply_theme(self)
        self._build_layout()
        self.show_page(keep_page)
        if keep_bottom:
            self.show_bottom(keep_bottom)

        new_editor = self.pages.get("editor")
        if editor_snap and new_editor is not None and hasattr(new_editor, "restore"):
            try:
                new_editor.restore(editor_snap)
            except Exception:
                pass
        new_chat = getattr(self, "chat_panel", None)
        if new_chat is not None and chat_session is not None:
            new_chat.session = chat_session
            if chat_cache is not None:
                new_chat._sessions_cache = chat_cache
            render = getattr(new_chat, "_render_messages", None)
            if callable(render):
                try:
                    render()
                except Exception:
                    pass

    # ------------------------------------------------------------- layouts
    def current_layout(self):
        """Snapshot the current arrangement as a LayoutState."""
        from .layouts import LayoutState

        geometry = ""
        try:
            geometry = str(self.geometry() or "")
        except Exception:
            geometry = ""
        try:
            bottom_height = int(self.settings.bottom_height or 210)
        except (TypeError, ValueError):
            bottom_height = 210
        return LayoutState(
            page=self._current_page or "editor",
            bottom_visible=bool(getattr(self, "_bottom_visible", True)),
            bottom_view=self._bottom_view or "terminal",
            geometry=geometry,
            sidebar_side=str(getattr(self.settings, "sidebar_side", "left")
                             or "left"),
            chat_side=str(getattr(self.settings, "chat_side", "right")
                          or "right"),
            bottom_height=bottom_height)

    def apply_layout(self, state):
        """Restore an arrangement saved earlier or a named preset."""
        try:
            self.show_page(state.page)
            if bool(state.bottom_visible) != bool(
                    getattr(self, "_bottom_visible", True)):
                self.toggle_bottom()
            if state.bottom_visible:
                self.show_bottom(state.bottom_view or "terminal")
            self.settings.sidebar_side = state.sidebar_side
            self.settings.chat_side = state.chat_side
            self.settings.bottom_height = int(state.bottom_height or 210)
            self._pack_docks()
            self.bottom.configure(
                height=max(80, min(800, int(state.bottom_height or 210))))
            if state.geometry:
                self.geometry(state.geometry)
        except Exception:
            return
        self.settings.active_layout = "custom"
        self.save_settings()

    def _bind_shortcuts(self):
        from .hotkeys import case_variants, resolve_hotkeys

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
        self._bound_hotkeys = []
        for action_id, handler in actions.items():
            sequence = bindings.get(action_id)
            if not sequence:
                continue
            for variant in case_variants(sequence):
                self.bind_all(variant, handler)
                self._bound_hotkeys.append(variant)

    def rebind_hotkeys(self):
        """Unbind old sequences and bind the current ones (live apply)."""
        for sequence in getattr(self, "_bound_hotkeys", []):
            try:
                self.unbind_all(sequence)
            except Exception:
                pass
        self._bound_hotkeys = []
        self._bind_shortcuts()

    def open_command_palette(self, mode: str = "commands"):
        from .ui_palette import open_command_palette

        return open_command_palette(self, mode)

    def refresh_current(self):
        page = self.pages.get(self._current_page)
        on_show = getattr(page, "on_show", None) if page is not None else None
        if callable(on_show):
            on_show()
            self.set_status(t('Обновлено: ') + self._current_page)

    def toggle_theme(self, name: str | None = None):
        """Switch between the light and dark palettes live."""
        from .theme import PALETTES, current_theme, set_palette
        from .theme import C as live_colors

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
            status.set(t('Текущая тема: ') + (t('тёмная') if target == "dark"
                                           else t('светлая')) + ".")
        self.set_status(t('Тема: ') + (t('тёмная') if target == "dark" else t('светлая'))
                        + t(' · переключение сохранено'))

    def show_shortcuts_help(self):
        messagebox.showinfo(
            t('Горячие клавиши'),
            t('Ctrl+1…Ctrl+9 — страницы (редактор, папка, модели, датасеты,\n   модель, playground, обучение, GPU, серверы)\nCtrl+0 — настройки\nCtrl+P — быстрое открытие файла\nCtrl+Shift+P — палитра команд\nCtrl+Shift+F — поиск по проекту\nCtrl+K — фокус в чат наставника\nCtrl+J — свернуть/развернуть нижнюю панель\nCtrl+Shift+M — панель «Проблемы»\nCtrl+W — закрыть вкладку редактора\nCtrl+Tab — следующая вкладка редактора\nCtrl+F / Ctrl+H — поиск и замена в редакторе\nF3 / Shift+F3 — следующее/предыдущее совпадение\nCtrl+F2 — закладка, F2 / Shift+F2 — между закладками\nCtrl+G — перейти к строке; Ctrl+Shift+G — панель Git\nCtrl+\\ — разделённый вид; Ctrl++ / Ctrl+- — масштаб шрифта\nF5 — обновить текущую страницу\nF1 — эта справка\nCtrl+Enter — отправить сообщение в чате\nCtrl+S — сохранить файл в редакторе'),
            parent=self)

    def _schedule_sidebar_label_refresh(self):
        """Coalesce resize notifications before fitting navigation labels."""
        if getattr(self, "_sidebar_refresh_after", None):
            return
        try:
            self._sidebar_refresh_after = self.after_idle(
                self._refresh_sidebar_labels)
        except Exception:
            self._sidebar_refresh_after = None

    def _refresh_sidebar_labels(self):
        """Measure sidebar labels against their actual width and truncate safely."""
        self._sidebar_refresh_after = None
        if not self._nav_buttons:
            return

        from tkinter import font as tkfont

        from .ui_patterns import nav_icon, nav_label

        try:
            sidebar_width = int(self._sidebar_frame.winfo_width() or 0)
        except Exception:
            sidebar_width = 0
        if sidebar_width < 20:
            sidebar_width = 64 if self._sidebar_compact else 216

        for key, button in self._nav_buttons.items():
            _key, label = self._nav_meta.get(key, (key, key))
            badge = self._nav_badges.get(key, "")
            full_text = nav_label(
                key, label, compact=self._sidebar_compact, badge=badge)
            if self._sidebar_compact:
                button.configure(text=full_text)
                continue

            try:
                button_width = int(button.winfo_width() or 0)
            except Exception:
                button_width = 0
            available = max(28, (button_width or sidebar_width - 4) - 20)
            try:
                font = tkfont.Font(root=self, font=button.cget("font"))
                fitted = full_text
                if font.measure(full_text) > available:
                    prefix = f"{nav_icon(key)}  "
                    suffix = f"  · {badge}" if badge else ""
                    visible = label.rstrip()
                    fitted = prefix + visible + "…" + suffix
                    while visible and font.measure(fitted) > available:
                        visible = visible[:-1].rstrip()
                        fitted = (
                            prefix + visible + "…" + suffix
                            if visible else nav_icon(key) + "…" + suffix
                        )
                    if font.measure(fitted) > available and suffix:
                        suffix = ""
                        visible = label.rstrip()
                        fitted = prefix + visible + "…"
                        while visible and font.measure(fitted) > available:
                            visible = visible[:-1].rstrip()
                            fitted = (
                                prefix + visible + "…" if visible
                                else nav_icon(key)
                            )
                    if font.measure(fitted) > available:
                        fitted = nav_icon(key)
                button.configure(text=fitted)
            except Exception:
                button.configure(text=full_text)

    def _make_nav_item(self, parent, key: str, label: str):
        row = tk.Frame(parent, bg=C["sidebar"])
        row.pack(fill="x")
        accent = tk.Frame(row, bg=C["sidebar"], width=4)
        accent.pack(side="left", fill="y")
        from .ui_patterns import nav_label as _nav_label

        btn = tk.Label(row, text=_nav_label(
            key, label,
            compact=bool(getattr(self.settings, "sidebar_compact", False))),
                       bg=C["sidebar"], fg=C["sidebar_fg"],
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
        self._nav_meta[key] = (key, label)
        from .hotkeys import DEFAULT_HOTKEYS
        from .ui_common import attach_tooltip

        _action = DEFAULT_HOTKEYS.get(f"page.{key}")
        attach_tooltip(btn, _nav_label(key, label, compact=False)
                       + (f" ({_action.default_key})" if _action else ""))

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
        if self._closing:
            self.set_status(t('Приложение закрывается'))
            return
        self.set_status(label + "…")

        def work():
            try:
                result = task()
                self.post_event("result", {"ok": True, "label": label, "value": result,
                                           "callback": on_success})
            except Exception as exc:
                log_worker_error("worker", exc)
                self.post_event("result", {"ok": False, "label": label, "error": str(exc),
                                           "on_error": on_error})

        try:
            self.executor.submit(work)
        except RuntimeError:
            self.set_status(t('Приложение закрывается'))

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
                except Exception as exc:
                    self.set_status(t('Ошибка обработки события: {exc}').format(exc=exc))
        except queue.Empty:
            pass
        self._night_watch_maybe()
        self.refresh_status_badges()
        self.after(100, self._poll_events)

    # --------------------------------------------------- UX patterns (28)
    def toggle_sidebar_compact(self):
        """Activity-bar mode: icon-only sidebar (VS Code style)."""
        from .ui_patterns import nav_label as _nav_label

        self._sidebar_compact = not self._sidebar_compact
        try:
            self.settings.sidebar_compact = bool(self._sidebar_compact)
            self.save_settings()
        except Exception:
            pass
        try:
            self._sidebar_frame.configure(
                width=64 if self._sidebar_compact else 216)
            self._compact_btn.configure(
                text="»" if self._sidebar_compact else "«")
        except Exception:
            pass
        for key, btn in self._nav_buttons.items():
            _k, label = self._nav_meta.get(key, (key, key))
            btn.configure(text=_nav_label(
                key, label, compact=self._sidebar_compact,
                badge=self._nav_badges.get(key, "")))
        self._schedule_sidebar_label_refresh()
        return self._sidebar_compact

    def set_nav_badge(self, key: str, badge: str):
        from .ui_patterns import nav_label as _nav_label

        self._nav_badges[key] = str(badge or "")
        btn = self._nav_buttons.get(key)
        if btn is not None:
            _k, label = self._nav_meta.get(key, (key, key))
            btn.configure(text=_nav_label(
                key, label, compact=self._sidebar_compact,
                badge=self._nav_badges[key]))
            self._schedule_sidebar_label_refresh()

    def refresh_status_badges(self):
        from .ui_status import refresh_status_badges as _impl

        return _impl(self)

    # ------------------------------------------------------- night watch
    # ------------------------------------------------------- night watch
    def night_watch_log(self):
        from .ui_night import night_watch_log as _impl

        return _impl(self)

    def _night_watch_maybe(self) -> None:
        from .ui_night import night_watch_maybe as _impl

        return _impl(self)

    def run_night_check(self):
        from .ui_night import run_night_check as _impl

        return _impl(self)

    def morning_report_text(self) -> str:
        from .ui_night import morning_report_text as _impl

        return _impl(self)

    def _handle_event(self, kind: str, payload: dict):
        if kind == "confirm":
            answer = messagebox.askyesno(payload.get("title", t('Подтверждение')),
                                         payload.get("message", ""), parent=self)
            payload["box"]["ok"] = answer
            payload["event"].set()
            return
        if kind == "progress":
            text = str(payload.get("text", "") or "")
            if text:
                self.set_status(text)
            return
        if kind == "budget":
            verdict = payload.get("verdict")
            if verdict is not None:
                self._on_budget_event(verdict)
            return
        if kind == "info":
            messagebox.showinfo(payload.get("title", "EGO"),
                                payload.get("message", ""), parent=self)
            return
        if kind == "chat_event":
            handler = getattr(self.chat_panel, "on_agent_event", None)
            if callable(handler):
                handler(payload.get("kind", ""), payload.get("payload", {}))
            return
        if kind == "result":
            if payload.get("ok"):
                self.set_status(t('Готово: ') + str(payload.get("label", "")))
                callback = payload.get("callback")
                if callback:
                    try:
                        callback(payload.get("value"))
                    except Exception as exc:
                        log_worker_error("callback", exc)
                        self.set_status(t('Ошибка обработки результата'))
                        messagebox.showerror("EGO",
                                             t('Операция завершилась, но интерфейс не смог обновить результат: {exc}').format(exc=exc), parent=self)
            else:
                self.set_status(t('Ошибка: ') + str(payload.get("label", "")))
                messagebox.showerror("EGO",
                                     str(payload.get("error", t('Неизвестная ошибка'))),
                                     parent=self)
                on_error = payload.get("on_error")
                if on_error:
                    try:
                        on_error(payload.get("error", ""))
                    except Exception as exc:
                        log_worker_error("on_error", exc)

    # -------------------------------------------------------------- helpers
    def save_settings(self):
        self.settings.save()
        self._refresh_workspace_badge()

    def catalog_entry(self, model_id: str):
        """Find a model catalog entry by id or name (None if absent)."""
        try:
            entries = self.model_registry().load()
        except Exception:
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
        context = ReportContext(title=t('Отчёт по обучению — EGO'))
        entry = None
        for candidate in self.model_registry().load():
            if candidate.id == self.settings.active_model_id:
                entry = candidate
                break
        context.model_info = {
            t('Модель'): entry.name if entry else self.settings.active_model_id or "—",
            t('Тип'): entry.kind if entry else "—",
            t('Расположение'): entry.location if entry else "—",
            t('Команда обучения'): self.settings.training_command or "—",
        }
        context.metrics_lines = [
            f"- {key}: {value:g}" for key, value in sorted(summary.last.items())]
        if summary.trend:
            context.metrics_lines.append(
                t('- тренды: ') + ", ".join(f"{k}={v}"
                                         for k, v in summary.trend.items()))
        context.eval_lines = build_eval_report(self.training.tail()).lines()
        status = self.training.status()
        context.watchdog_lines = [
            issue.line() for issue in detect_issues(
                summary, running=status.running)]
        context.plan_tasks = list(self.agent_tasks or
                                  [{"title": task, "status": "pending"}
                                   for task in self.agent_plan])
        context.activity_lines = [
            f"{item.kind}: {item.summary[:120]}"
            for item in self.activity.recent(15)]
        report = self.reports.latest()
        if report is not None and not report.is_empty():
            if report.score is not None:
                context.assessment_lines.append(t('Оценка: {v1:g}/10').format(v1=report.score))
            for label, items in ((t('Сильные стороны'), report.strengths),
                                 (t('Слабые стороны'), report.weaknesses),
                                 (t('Риски'), report.risks),
                                 (t('Рекомендации'), report.recommendations)):
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
        except Exception:
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
                    self.set_status(t('⚠ Watchdog: критическая проблема обучения'))
            else:
                self._watchdog_tail = (0, 0.0)
                self.watchdog.reset()
        except Exception:
            pass
        try:
            self.after(15_000, self._watchdog_tick)
        except Exception:
            pass

    # ------------------------------------------------------- budget daemon
    BUDGET_TICK_MS = 120_000

    def _start_budget_daemon(self):
        """Фоновый страж бюджета: автостоп подов без открытия страницы GPU."""
        if self._budget_daemon_started:
            return
        self._budget_daemon_started = True
        try:
            self.after(60_000, self._budget_tick)
        except Exception:
            pass

    def _budget_tick(self):
        try:
            cap = float(self.settings.cloud_total_budget_usd or 0.0)
        except (TypeError, ValueError):
            cap = 0.0
        if cap > 0 and not self._closing:
            try:
                self.executor.submit(self._budget_work, cap)
            except Exception:
                pass
        try:
            self.after(self.BUDGET_TICK_MS, self._budget_tick)
        except Exception:
            pass

    def _budget_work(self, cap: float):
        """Runs in the executor: list pods, enforce the cap, report."""
        from .budget_guard import BudgetLedger, apply_guard

        try:
            client = self.runpod_client()
            pods = client.list_pods()
        except Exception:
            # Молчать вечно нельзя: после 3 недоступных циклов пользователь
            # должен знать, что автостоп сейчас НЕ работает.
            self._budget_api_fails = getattr(self, "_budget_api_fails", 0) + 1
            if self._budget_api_fails == 3:
                from .budget_guard import BudgetVerdict

                self.post_event("budget", {"verdict": BudgetVerdict(
                    cap_usd=cap, spent_usd=0.0, over=False,
                    warning=t('RunPod API недоступен 3 цикла подряд — '
                              'автостоп бюджета временно НЕ работает, '
                              'расходы не контролируются'))})
            return
        self._budget_api_fails = 0
        ledger = BudgetLedger.load()

        def stopper(pod_id):
            client.pod_action(pod_id, "stop", confirmed=True)

        verdict = apply_guard(ledger, pods, cap, stopper=stopper)
        if verdict.stopped or verdict.warning:
            self.post_event("budget", {"verdict": verdict})

    def _on_budget_event(self, verdict) -> None:
        self.activity.log(
            "cloud",
            t('Бюджетный страж остановил поды: {v1}').format(
                v1=", ".join(verdict.stopped)),
            ok=False)
        self.set_status(t('⛔ Бюджет: ') + verdict.render())

    def _refresh_workspace_badge(self):
        path = (self.settings.workspace_path or "").strip()
        self.workspace_badge.set(t('папка: {v1}').format(v1=Path(path).name) if path else t('папка не выбрана'))
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
            except Exception:
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
                t('Настройте провайдера, модель и API-ключ на странице «Настройки».')
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
            if not command.strip():
                return {"ok": False,
                        "error": t('Команда обучения не задана: передайте '
                                   'command (например, python train_llm.py) '
                                   'или сгенерируйте скрипт в мастере.')}
            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": t('Рабочая папка не выбрана.')}
            try:
                log_path = self.training.start(command, root)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            record = self.runs.start(command, str(root), log_path)
            self.watchdog.reset()
            self.activity.log("training", t('Агент запустил обучение: {command}').format(command=command),
                              run_id=record.id)
            return {"ok": True, "log_path": log_path, "run_id": record.id}

        def stop_training(_args):
            if not self.training.status().running:
                return {"ok": True, "note": t('Обучение не запущено.')}
            try:
                self.training.stop()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log("training", t('Агент остановил обучение'))
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
            except Exception:
                entry = None
            config_data: object = None
            if root is not None:
                config_file = Path(root) / "config.json"
                if config_file.is_file():
                    try:
                        config_data = json.loads(
                            config_file.read_text(encoding="utf-8"))
                    except Exception:
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
            except Exception as exc:
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
                return {"ok": False, "error": t('Рабочая папка не выбрана.')}
            from .training import CONTROL_KEYS
            from .training import read_control as read_hot_control

            return {"ok": True, "control": read_hot_control(root),
                    "keys": list(CONTROL_KEYS)}

        def set_training_control(args):
            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": t('Рабочая папка не выбрана.')}
            from .training import write_control

            params = {key: value for key, value in (args or {}).items()
                      if value is not None}
            try:
                current = write_control(root, params)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log(
                "training",
                t('Агент скорректировал обучение: ')
                + ", ".join(f"{key}={value}" for key, value in params.items()),
            )
            return {"ok": True, "control": current,
                    "note": t('Изменения применяются со следующей эпохи обучения.')}

        def set_plan(args):
            steps = args.get("steps") or []
            if not isinstance(steps, list) or not steps:
                return {"ok": False, "error": t('План должен содержать шаги.')}
            clean = [str(step).strip()[:200] for step in steps if str(step).strip()][:12]
            self.agent_plan = clean
            self.agent_tasks = [{"title": step, "status": "pending"} for step in clean]
            self.activity.log("plan", t('План агента:\n- ') + "\n- ".join(clean))
            return {"ok": True, "steps": clean}

        def update_plan(args):
            raw_steps = args.get("steps") or []
            if not isinstance(raw_steps, list) or not raw_steps:
                return {"ok": False, "error": t('План должен содержать шаги.')}
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
                return {"ok": False, "error": t('План должен содержать шаги.')}
            self.agent_tasks = tasks
            self.agent_plan = [task["title"] for task in tasks]
            marks = {"done": "✓", "failed": "✗", "in_progress": "▶", "pending": "○"}
            self.activity.log("plan", t('План агента:\n') + "\n".join(
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
                    "note": t('Применяй выбранные параметры через set_training_control.')}

        def compare_runs(args):
            from .compare import compare_runs as _compare
            from .compare import overlay_series

            key = str(args.get("key") or "loss")
            records = [record for record in self.runs.list(10)
                       if record.log_path and Path(record.log_path).is_file()]
            if len(records) < 2:
                return {"ok": False,
                        "error": t('Нужны два завершённых запуска с логами.')}
            first, second = records[0], records[1]
            summary_a = parse_log(Path(first.log_path).read_text(
                encoding="utf-8", errors="replace"))
            summary_b = parse_log(Path(second.log_path).read_text(
                encoding="utf-8", errors="replace"))
            report = _compare(summary_a, summary_b,
                              label_a=t('Запуск 1'), label_b=t('Запуск 2'))
            return {"ok": True,
                    "run_a": first.command, "run_b": second.command,
                    "series": overlay_series(key, summary_a, summary_b),
                    "winner": report.winner,
                    "lines": report.lines()}

        def prepare_dataset(args):
            from .datasets import (
                DatasetError,
                filter_rows,
                read_rows,
                split_rows,
                write_rows,
            )

            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": t('Рабочая папка не выбрана.')}
            rel = str(args.get("path") or "")
            source = Path(root) / rel
            if not source.is_file():
                return {"ok": False, "error": t('Файл не найден: {rel}').format(rel=rel)}
            fmt = source.suffix.lstrip(".").lower()
            if fmt not in {"jsonl", "json", "csv", "tsv", "txt"}:
                return {"ok": False, "error": t('Неподдерживаемый формат: {fmt}').format(fmt=fmt)}
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
                              t('Агент разбил датасет: ')
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
                        "error": t('Облачную модель нельзя экспортировать локально.')}
            fmt = str(args.get("format") or "gguf").lower()
            library = self.model_registry().library_dir
            request = ExportRequest(
                source=source, fmt=fmt,
                output_dir=str(Path(library) / "exports"),
                out_type=str(args.get("out_type") or "f16"))
            result = run_export(request)
            self.activity.log(
                "model",
                t('Экспорт {fmt}: ').format(fmt=fmt) + (t('успешно') if result.ok else result.error))
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
                t('Квантизация {quant_type}: ').format(quant_type=quant_type)
                + (t('успешно') if result.ok else result.error))
            return {"ok": result.ok, "recipe": quant_type,
                    "command": result.command, "output_path": result.output_path,
                    "checks": result.checks, "error": result.error}

        def benchmark_model(args):
            from .bench import (
                BenchResult,
                BenchStore,
                format_bench_table,
                rank_benchmarks,
                run_benchmark,
            )

            entry = self.catalog_entry(str(args.get("model_id") or ""))
            command = str(args.get("command") or "").strip()
            try:
                iterations = max(1, min(int(args.get("iterations") or 3), 10))
            except (TypeError, ValueError):
                iterations = 3
            if command:
                result = run_benchmark(t('команда'), command, iterations=iterations)
            elif entry and entry.base_url:
                client = _endpoint_client(entry)
                durations: list[int] = []
                tokens_chars = 0
                error = ""
                for _ in range(iterations):
                    try:
                        probe = client.generate(t('Скажи «ок».'), max_tokens=8,
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
                        "error": t('Укажите model_id (модель с endpoint) или command.')}
            library = self.model_registry().library_dir
            BenchStore(library).add(result)
            self.activity.log("bench", result.line())
            return {"ok": result.ok(), "line": result.line(),
                    "table": format_bench_table([result]),
                    "rank": rank_benchmarks([result]),
                    "error": result.error}

        def run_prompt_suite(args):
            from .prompt_suite import (
                default_suite,
                format_suite_report,
                load_suite,
                run_suite,
            )

            entry = self.catalog_entry(str(args.get("model_id") or ""))
            if entry and entry.base_url:
                client = _endpoint_client(entry)
                model_name = entry.name
            else:
                settings = self.settings
                if not (settings.mentor_base_url and settings.mentor_model):
                    return {"ok": False,
                            "error": t('Нужна модель с endpoint (model_id) или настроенный провайдер.')}
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
                                "error": t('Рабочая папка не выбрана.')}
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
            self.activity.log("suite", t('Промпт-набор: {v1}/{v3}').format(v1=result.passed, v3=result.total))
            return {"ok": True, "model": model_name,
                    "passed": result.passed, "total": result.total,
                    "mean_latency_ms": result.mean_latency_ms,
                    "report": format_suite_report(result)}

        def export_report(args):
            from .report_export import save_report

            root = self.workspace_root()
            if root is None:
                return {"ok": False, "error": t('Рабочая папка не выбрана.')}
            rel = str(args.get("path") or "reports/report")
            fmt = str(args.get("format") or "md").lower()
            try:
                exported = save_report(Path(root) / rel, self.build_report_context(),
                                       fmt=fmt)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log("report", t('Отчёт сохранён: {v1}').format(v1=exported.path))
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
                # Validate the credential/client before writing anything to the
                # persistent queue. A missing key must be a side-effect-free
                # refusal, not a failed job left behind in the queue.
                key = self.secrets.get("runpod_api_key")
                client = RunPodClient(key)
                job = CloudJob(
                    name=str(args.get("name") or t('задание')),
                    command=str(args.get("command") or ""),
                    image=str(args.get("image") or
                              "runpod/pytorch:2.8.0-py3.11-cuda12.8.1"),
                    gpu_id=str(args.get("gpu_id") or ""),
                    max_gpu_hourly_usd=float(
                        args.get("max_gpu_hourly_usd") or 0.0),
                    container_disk_gb=int(args.get("container_disk_gb") or 30))
                queue = CloudJobQueue(self.model_registry().library_dir)
                queue.add(job)
                queued = queue.submit(job.id, client)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self.activity.log("cloud", t('Облачное задание: {v1}').format(v1=queued.line()))
            return {"ok": queued.status == "submitted", "job": queued.line(),
                    "status": queued.status, "pod_id": queued.pod_id,
                    "error": queued.error}

        def spawn_subagent(args):
            if not self.settings.agent_subagents:
                return {"ok": False, "error": t('Подагенты отключены в настройках агента.')}
            goal = str(args.get("goal") or "").strip()
            if not goal:
                return {"ok": False, "error": t('Укажите подзадачу (goal).')}
            try:
                steps = max(2, min(int(args.get("max_steps", 6)), 10))
            except (TypeError, ValueError):
                steps = 6
            try:
                from .agent import MODEL_TOOLS_SCHEMAS as _MTS
                from .agent import TRAINING_CONTEXT_TOOL_SCHEMAS as _TCS
                from .agent import MentorAgent
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
                "description": t('Запустить обучение в рабочей папке (командой из настроек или из аргумента command).'),
                "parameters": {"type": "object", "properties": {
                    "command": {"type": "string"}}, "required": []}}},
            {"type": "function", "function": {
                "name": "stop_training",
                "description": t('Остановить текущее обучение.'),
                "parameters": {"type": "object", "properties": {}, "required": []}}},
            {"type": "function", "function": {
                "name": "run_diagnostics",
                "description": t('Проверка окружения: Python, хранилище ключей, SSH, Git, рабочая папка, диск, настройки наставника.'),
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
        except Exception:
            pass

        try:
            srv_handlers, srv_schemas, srv_mutations = \
                self.server_manager().agent_tools()
            handlers.update(srv_handlers)
            schemas.extend(srv_schemas)
            mutations |= set(srv_mutations)
        except Exception:
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
                        "error": t('Гостевой режим (роль «гость»): действие недоступно.')}

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
                t('Модель: {v1} ({v3})').format(v1=entry.name, v3=entry.kind),
                t('Путь/URI: {v1}').format(v1=entry.location),
                f"API model id: {entry.model_id or '—'}",
                t('Заметки: {v1}').format(v1=entry.notes or '—'),
                "",
            ]
        else:
            lines += [t('Модель не выбрана в каталоге.'), ""]

        status = self.training.status()
        summary = parse_log(self.training.tail())
        lines += [
            t('Обучение: {v1}').format(v1=t('выполняется') if status.running else t('остановлено')),
            t('Команда: {v1}').format(v1=status.command or '—'),
            t('Код возврата: {v1}').format(v1=status.returncode),
            t('Метрики: {v1}').format(v1=metrics_brief(summary)),
        ]
        if summary.anomalies:
            lines.append(t('Аномалии: ') + "; ".join(summary.anomalies))
        recent_runs = self.runs.list(5)
        if recent_runs:
            lines.append("")
            lines.append(t('Последние запуски:'))
            for record in recent_runs:
                lines.append(
                    t('- {v1} → {v3}; метрики: {v5}').format(v1=record.command, v3=record.status_ru, v5=record.metrics_last or '—')
                )
        tail = self.training.tail(6000)
        if tail.strip():
            lines += ["", t('Хвост лога:'), "```", tail, "```"]
        return "\n".join(lines)

    def assessment_prompt(self) -> str:
        return REPORT_PROMPT_TEMPLATE.format(context=self.assessment_context())

    # ---------------------------------------------------------------- close
    def _on_close(self):
        self._closing = True
        try:
            self.closing_event.set()  # выполняющиеся задачи проверяют и сворачиваются
        except Exception:
            pass
        try:
            self.training.stop()
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main():
    app = TrainingHubApp()
    app.mainloop()
