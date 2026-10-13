"""Tkinter IDE shell: sidebar, center workspace, bottom terminal, right chat."""
from __future__ import annotations

import queue
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

from . import ui_common
from .activity import ActivityLog
from .agent import TRAINING_CONTEXT_TOOL_SCHEMAS
from .cloud_gpu import RunPodClient
from .config import AppSettings, SecretStore, app_data_dir
from .connectors import ConnectorManager
from .git_manager import GitRepositoryManager
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
        self.title("AlterEgo Training Hub — LLM Studio")
        self.geometry("1480x860")
        self.minsize(1180, 720)

        self.settings = AppSettings.load()
        self.secrets = SecretStore()
        self.git = GitRepositoryManager(timeout_seconds=600)
        self.training = TrainingRun()
        self.runs = RunStore()
        self.activity = ActivityLog()
        self.reports = ReportStore()
        self.servers = ServerStore()
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
        self.status_bar = tk.Frame(self, bg="#e8edf5")
        self.status_bar.pack(side="bottom", fill="x")
        self.status_text = tk.StringVar(value="Готово")
        tk.Label(self.status_bar, textvariable=self.status_text, bg="#e8edf5",
                 fg=C["muted"], font=ui_common.F_SMALL, anchor="w",
                 padx=12).pack(side="left", fill="x", expand=True)
        self.workspace_badge = tk.StringVar(value="папка не выбрана")
        tk.Label(self.status_bar, textvariable=self.workspace_badge, bg="#e8edf5",
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
        from .ui_servers import ServersPage
        from .ui_settings import SettingsPage
        from .ui_terminal import TerminalPanel
        from .ui_training import TrainingPage
        from .ui_workspace import WorkspacePage
        from .ui_connectors import ConnectorsPage

        page_classes = [
            ("editor", EditorPage),
            ("workspace", WorkspacePage),
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

        self.terminal = TerminalPanel(center, self)
        self.terminal.pack(side="bottom", fill="x", pady=(0, 2))
        self.terminal.configure(height=190)
        self.terminal.pack_propagate(False)

        self.show_page("editor")
        self._refresh_workspace_badge()

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

        handlers = {
            "get_training_status": get_training_status,
            "read_training_log": read_training_log,
            "get_run_history": get_run_history,
            "start_training": start_training,
            "stop_training": stop_training,
        }
        schemas = list(TRAINING_CONTEXT_TOOL_SCHEMAS) + [
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
        ]
        mutations = {"start_training", "stop_training"}

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
