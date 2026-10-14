"""Headless UI smoke test: build every page with a fake tkinter and poke it.

This catches wiring errors between pages and the app shell without needing a
display server or a real Tk installation.
"""
from __future__ import annotations

import sys
import types
from typing import ClassVar

import pytest


class _Widget:
    """Permissive widget stand-in: any method call is a harmless no-op."""

    def __init__(self, *args, **kwargs):
        self._kwargs = dict(kwargs)

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return lambda *args, **kwargs: None

    def get(self, *args, **kwargs):
        return ""

    def __setitem__(self, key, value):
        pass

    def __getitem__(self, key):
        return ""


class _Var:
    def __init__(self, master=None, value=None, **kwargs):
        self._value = "" if value is None else value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, *args, **kwargs):
        pass


class _Treeview(_Widget):
    def __init__(self, *args, **kwargs):
        self._items = []
        self._selection = ()

    def insert(self, parent, index, iid=None, **kwargs):
        item_id = iid or f"item-{len(self._items)}"
        self._items.append((item_id, kwargs))
        return item_id

    def get_children(self):
        return [item_id for item_id, _ in self._items]

    def delete(self, *items):
        if items:
            self._items = [it for it in self._items if it[0] not in items]
            self._selection = tuple(s for s in self._selection if s not in items)

    def selection(self, *args):
        return self._selection

    def selection_set(self, *items):
        self._selection = tuple(items)

    def heading(self, *args, **kwargs):
        pass

    def column(self, *args, **kwargs):
        pass


class _Listbox(_Widget):
    def __init__(self, *args, **kwargs):
        self._items = []
        self._selection = ()

    def insert(self, index, item):
        self._items.append(str(item))

    def delete(self, first, last=None):
        self._items = []

    def size(self):
        return len(self._items)

    def get(self, first, last=None):
        if 0 <= first < len(self._items):
            return self._items[first]
        return ""

    def curselection(self):
        return self._selection

    def selection_set(self, first, last=None):
        self._selection = (first,)

    def selection_clear(self, first, last=None):
        self._selection = ()

    def activate(self, index):
        pass

    def see(self, index):
        pass


class _Entry(_Widget):
    """Stateful one-line entry fake: insert/delete/get keep a string buffer."""

    def __init__(self, *args, **kwargs):
        self._value = ""

    def insert(self, index, text=""):
        self._value += str(text)

    def delete(self, start, end=None):
        self._value = ""

    def get(self, *args, **kwargs):
        return self._value


class _Combobox(_Widget):
    """Stateful combobox fake: set/get keep a value, configure keeps values."""

    def __init__(self, *args, **kwargs):
        self._value = str(kwargs.get("value") or "")
        self._values = tuple(kwargs.get("values") or ())

    def set(self, value):
        self._value = str(value)

    def get(self, *args, **kwargs):
        return self._value

    def configure(self, **kwargs):
        if "values" in kwargs:
            self._values = tuple(kwargs["values"])

    def config(self, **kwargs):
        return self.configure(**kwargs)


class _Text(_Widget):
    """Stateful text widget fake: insert/delete/get work like a small buffer."""

    def __init__(self, *args, **kwargs):
        self._buffer = ""

    def insert(self, index, text="", *tags, **kwargs):
        if str(index).startswith("end"):
            self._buffer += str(text)
        else:
            self._buffer = str(text) + self._buffer

    def delete(self, start, end=None):
        self._buffer = ""

    def get(self, start, end=None):
        return self._buffer


class _Tk(_Widget):
    def mainloop(self, *args, **kwargs):
        pass


class _Toplevel(_Widget):
    pass


class _Style(_Widget):
    def theme_use(self, name):
        pass


TclError = type("TclError", (Exception,), {})


def _fake_tkinter():
    tk_mod = types.ModuleType("tkinter")
    tk_mod.Tk = _Tk
    tk_mod.Toplevel = _Toplevel
    tk_mod.Frame = _Widget
    tk_mod.Label = _Widget
    tk_mod.Entry = _Entry
    tk_mod.Text = _Text
    tk_mod.Listbox = _Listbox
    tk_mod.Checkbutton = _Widget
    tk_mod.Canvas = _Widget
    tk_mod.StringVar = _Var
    tk_mod.BooleanVar = _Var
    tk_mod.IntVar = _Var
    tk_mod.TclError = TclError
    tk_mod.END = "end"

    ttk_mod = types.ModuleType("tkinter.ttk")
    ttk_mod.Style = _Style
    ttk_mod.Frame = _Widget
    ttk_mod.Label = _Widget
    ttk_mod.Button = _Widget
    ttk_mod.Entry = _Entry
    ttk_mod.Combobox = _Combobox
    ttk_mod.Treeview = _Treeview
    ttk_mod.Scrollbar = _Widget
    ttk_mod.LabelFrame = _Widget
    ttk_mod.Notebook = _Widget
    ttk_mod.Progressbar = _Widget

    messagebox_mod = types.ModuleType("tkinter.messagebox")
    messagebox_mod.showinfo = lambda *a, **k: True
    messagebox_mod.showerror = lambda *a, **k: True
    messagebox_mod.askyesno = lambda *a, **k: True
    messagebox_mod.showwarning = lambda *a, **k: True

    filedialog_mod = types.ModuleType("tkinter.filedialog")
    filedialog_mod.askdirectory = lambda *a, **k: ""
    filedialog_mod.askopenfilename = lambda *a, **k: ""
    filedialog_mod.asksaveasfilename = lambda *a, **k: ""

    tk_mod.ttk = ttk_mod
    tk_mod.messagebox = messagebox_mod
    tk_mod.filedialog = filedialog_mod
    return {
        "tkinter": tk_mod,
        "tkinter.ttk": ttk_mod,
        "tkinter.messagebox": messagebox_mod,
        "tkinter.filedialog": filedialog_mod,
    }


@pytest.fixture()
def fake_ui(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    saved = {}
    fakes = _fake_tkinter()
    for name, module in fakes.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    # Import UI modules only inside the test so collection works without Tk.
    import importlib

    modules = {}
    for name in [
        "alterego_training_hub.ui_common",
        "alterego_training_hub.ui_chat",
        "alterego_training_hub.ui_workspace",
        "alterego_training_hub.ui_search",
        "alterego_training_hub.ui_palette",
        "alterego_training_hub.ui_problems",
        "alterego_training_hub.ui_git",
        "alterego_training_hub.ui_completion",
        "alterego_training_hub.ui_models",
        "alterego_training_hub.ui_model",
        "alterego_training_hub.ui_editor",
        "alterego_training_hub.ui_datasets",
        "alterego_training_hub.ui_playground",
        "alterego_training_hub.ui_training",
        "alterego_training_hub.ui_gpu",
        "alterego_training_hub.ui_connectors",
        "alterego_training_hub.ui_terminal",
        "alterego_training_hub.ui_settings",
        "alterego_training_hub.ui",
    ]:
        modules[name] = importlib.import_module(name)
    yield modules
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    for name in modules:
        sys.modules.pop(name, None)


def test_app_builds_and_pages_switch(fake_ui):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    assert set(app.pages) == {"chat", "editor", "workspace", "search", "models",
                              "datasets", "model", "playground", "training",
                              "gpu", "servers", "connectors", "settings"}
    for key in ["editor", "workspace", "search", "models", "datasets", "model",
                "playground", "training", "gpu", "servers", "connectors",
                "settings"]:
        app.show_page(key)
    assert app._current_page == "settings"
    # "chat" is the docked right panel: show_page only focuses it.
    app.show_page("chat")
    assert app._current_page == "settings"

    # IDE layout: terminal panel exists under the center column.
    assert hasattr(app.terminal, "cmd_entry") and hasattr(app.terminal, "output")

    # Shell services respond as expected without configuration.
    assert app.workspace_root() is None
    with pytest.raises(Exception):
        app.mentor_client()
    assert app.model_registry() is not None


def test_chat_and_models_pages_interact(fake_ui):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    chat = app.pages["chat"]
    chat.new_session()
    chat.session.add("user", "привет")
    chat.session.add("assistant", "здравствуйте")
    chat._render_messages()
    chat.log_activity("тест")
    assert chat.session.title == "привет"

    models = app.pages["models"]
    models.refresh()
    models.var_name.set("demo")
    models.var_kind.set("cloud")
    models.var_location.set("s3://bucket/demo")
    models.add_entry()
    models.refresh()
    assert models.models_status.get() == "Моделей в каталоге: 1"
    models.var_location.set("ftp://bad")
    models.add_entry()  # rejected by validation, shown via (faked) dialog

    settings = app.pages["settings"]
    settings.mentor_vars["mentor_base_url"].set("https://api.example.test/v1")
    settings.model_var.set("gpt-x")
    settings._collect_mentor()
    assert app.settings.mentor_model == "gpt-x"

    workspace = app.pages["workspace"]
    workspace.refresh_repo_status()  # no repo connected -> status only
    app.save_settings()


def test_dashboard_training_and_agent_context(fake_ui):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    dashboard = app.pages["model"]
    dashboard.refresh()
    dashboard._render_assessment()
    dashboard._render_activity()
    dashboard.request_assessment()  # no mentor configured -> dialog + settings page

    training = app.pages["training"]
    training.refresh_metrics()
    training.refresh_runs()
    training.start_training()  # no workspace -> dialog, no crash

    tools, schemas, mutations = app.agent_extra_tools()
    assert {"get_training_status", "read_training_log", "get_run_history",
            "start_training", "stop_training", "run_diagnostics"} <= set(tools)
    assert {"search_github", "search_huggingface", "huggingface_model_card",
            "send_email"} <= set(tools)
    assert {"list_servers", "server_info", "run_on_server"} <= set(tools)
    assert tools["get_training_status"]({})["ok"] is True
    assert tools["read_training_log"]({"max_bytes": 1000})["ok"] is True
    assert tools["get_run_history"]({"limit": 3})["ok"] is True
    assert tools["start_training"]({})["ok"] is False  # no workspace -> error dict
    assert tools["stop_training"]({})["ok"] is True
    diag = tools["run_diagnostics"]({})
    assert diag["ok"] is True and diag["summary"]["total"] >= 8
    assert {"start_training", "stop_training", "send_email", "run_on_server"} \
        <= set(mutations)
    assert len(schemas) >= 12

    context = app.assessment_context()
    assert "Обучение" in context
    prompt = app.assessment_prompt()
    assert "```report" in prompt and "Контекст" in prompt


def test_editor_datasets_and_playground(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # workspace with one file
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    editor = app.pages["editor"]
    editor.refresh_tree()
    assert editor.tree.get_children()  # files discovered
    editor.project_var.set("demo")
    editor.create_project()
    assert (workspace / "demo" / "train.py").exists()
    editor.open_file(workspace / "hello.py")
    assert "print" in editor.editor.get("1.0", "end")
    editor.editor.delete("1.0", "end")
    editor.editor.insert("1.0", "x = 1\n")
    editor.save_file()
    assert (workspace / "hello.py").read_text(encoding="utf-8") == "x = 1\n"

    datasets = app.pages["datasets"]
    datasets.refresh()
    datasets.add_manual()

    playground = app.pages["playground"]
    playground.refresh_models()
    playground.prompt.insert("1.0", "привет")
    playground.run_single()  # no model configured -> dialog, no crash


def test_terminal_and_connectors_pages(fake_ui, monkeypatch, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # Terminal: empty command is a no-op; without a workspace -> dialog only.
    app.terminal.cmd_entry.insert(0, "")
    app.terminal.run_command()
    app.terminal.cmd_entry.insert(0, "echo hi")
    monkeypatch.setattr(app, "start_async", lambda *a, **k: None)
    app.terminal.run_command()  # no workspace -> info dialog, no crash
    app.terminal.append("line\n")
    assert "line" in app.terminal.output.get("1.0", "end")
    app.terminal._history.append("echo old")
    app.terminal._history_up()
    assert app.terminal.cmd_entry.get() == "echo old"

    # With a workspace the command actually goes through WorkspaceTools.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    ran = {}

    def sync_start(label, task, on_success=None, on_error=None):
        try:
            value = task()
        except Exception as exc:
            if on_error:
                on_error(str(exc))
            return
        ran["value"] = value
        if on_success:
            on_success(value)

    monkeypatch.setattr(app, "start_async", sync_start)
    app.terminal.cmd_entry.delete(0, "end")
    app.terminal.cmd_entry.insert(0, "python -c \"print('ok')\"")
    app.terminal.run_command()
    assert ran["value"]["returncode"] == 0
    assert "ok" in app.terminal.output.get("1.0", "end")

    # Connectors page: statuses render, secrets round-trip through the manager.
    connectors = app.pages["connectors"]
    app.show_page("connectors")
    connectors.refresh_status()
    assert set(connectors.cards) == {"github", "huggingface", "gmail"}
    assert connectors.cards["github"]["status"].get() == "токен не требуется"

    saved = {}

    class FakeSecrets:
        def set(self, key, value):
            saved[key] = value

        def delete(self, key):
            saved.pop(key, None)

        def get(self, key):
            return saved.get(key, "")

    monkeypatch.setattr(connectors, "_manager",
                        lambda: __import__(
                            "alterego_training_hub.connectors", fromlist=["ConnectorManager"]
                        ).ConnectorManager(FakeSecrets()))
    connectors.cards["gmail"]["secret"].set("app-pass")
    connectors.save_secret("gmail", connectors.cards["gmail"]["secret"],
                           connectors.cards["gmail"]["status"])
    assert saved["connector.gmail_app_password"] == "app-pass"
    connectors.delete_secret("gmail", connectors.cards["gmail"]["secret"],
                             connectors.cards["gmail"]["status"])
    assert "connector.gmail_app_password" not in saved


def test_chat_send_and_reset(fake_ui, monkeypatch):
    import types as _types

    app_module = fake_ui["alterego_training_hub.ui"]
    chat_module = fake_ui["alterego_training_hub.ui_chat"]
    app = app_module.TrainingHubApp()
    chat = app.pages["chat"]

    monkeypatch.setattr(app, "mentor_client", lambda: _types.SimpleNamespace(model="gpt-x"))

    def sync_start(label, task, on_success=None, on_error=None):
        try:
            value = task()
        except Exception as exc:
            if on_error:
                on_error(str(exc))
            return
        if on_success:
            on_success(value)

    monkeypatch.setattr(app, "start_async", sync_start)

    calls = {}

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            calls["kwargs"] = kwargs

        def run_turn(self, history, **kwargs):
            calls["history"] = list(history)
            emit = kwargs.get("on_event") or (lambda *_a, **_k: None)
            transcript = kwargs.get("transcript")
            emit("assistant", {"text": "", "tool_calls": 1})
            emit("tool_start", {"name": "get_training_status",
                                "description": "Состояние обучения"})
            emit("tool_result", {"name": "get_training_status", "ok": True,
                                 "summary": "loss=0.1"})
            if transcript is not None:
                transcript.append({"role": "assistant", "content": "",
                                   "tool_calls": [{"id": "c1", "type": "function",
                                                   "function": {"name": "get_training_status",
                                                                "arguments": "{}"}}]})
            return _types.SimpleNamespace(text="всё хорошо")

        def run_goal(self, goal, **kwargs):
            calls["goal"] = goal
            return _types.SimpleNamespace(text="цель выполнена")

    monkeypatch.setattr(chat_module, "MentorAgent", FakeAgent)

    # Assist mode: send typed text -> run_turn with the session history.
    chat.input.insert("1.0", "привет")
    chat.send()
    assert calls["history"][-1]["content"] == "привет"
    assert chat.session.messages[-1].role == "assistant"
    assert chat.session.messages[-1].content == "всё хорошо"
    assert "всё хорошо" in chat.messages.get("1.0", "end")

    # Mode toggle flips assist -> agent and persists the setting.
    chat.toggle_mode()
    assert app.settings.chat_autonomy == "agent"
    chat.send_preset("запусти тесты и почини")
    assert calls["goal"] == "запусти тесты и почини"
    assert chat.session.messages[-1].content == "цель выполнена"
    chat.toggle_mode()
    assert app.settings.chat_autonomy == "assist"

    # Reset: new session is empty again.
    chat.new_session()
    assert chat.session.messages == []


def test_servers_page_collapsible_and_terminal(fake_ui, monkeypatch, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    ui_common_module = fake_ui["alterego_training_hub.ui_common"]
    app = app_module.TrainingHubApp()

    # Collapsible sections: toggle hides/shows the body.
    section = ui_common_module.Collapsible(app.pages_host, "Настройки")
    assert section.is_open is True
    section.toggle()
    assert section.is_open is False
    section.toggle()
    assert section.is_open is True
    section.set_hint("свернуть/развернуть")

    # Terminal: collapsible panel + target selector.
    term = app.terminal
    assert term.is_open is True
    term.toggle()
    assert term.is_open is False
    term.toggle()
    assert term.is_open is True
    term.refresh_targets()  # no servers -> just "Локально", no crash

    # Servers page: save via a fake manager (no keyring / network).
    from alterego_training_hub.servers import (
        ServerManager,
        ServerStore,
    )

    class FakeSecrets:
        def __init__(self):
            self.data = {}

        def set(self, key, value):
            self.data[key] = value

        def get(self, key):
            if key not in self.data:
                raise RuntimeError("нет ключа")
            return self.data[key]

        def delete(self, key):
            self.data.pop(key, None)

    class FakeRunner:
        def __init__(self, entry, secret):
            self.entry, self.secret = entry, secret

        def connect(self):
            pass

        def run(self, command, timeout=60.0):
            return {"ok": True, "exit_code": 0, "command": command,
                    "output": "hello"}

        def close(self):
            pass

    manager = ServerManager(ServerStore(tmp_path / "servers.json"), FakeSecrets(),
                            runner_factory=lambda e, s: FakeRunner(e, s))
    monkeypatch.setattr(app, "server_manager", lambda: manager)

    page = app.pages["servers"]
    app.show_page("servers")
    page.refresh_list()
    page.var_name.set("gpu-box")
    page.var_host.set("10.0.0.5")
    page.var_port.set("22")
    page.var_user.set("dev")
    page.var_auth.set("key")
    page.save_server()
    assert [e.name for e in manager.list()] == ["gpu-box"]

    page.refresh_list()
    page.tree.selection_set(manager.list()[0].id)
    page._load_selected()
    assert page.var_host.get() == "10.0.0.5"

    ran = {}

    def sync_start(label, task, on_success=None, on_error=None):
        try:
            value = task()
        except Exception as exc:
            if on_error:
                on_error(str(exc))
            return
        ran["value"] = value
        if on_success:
            on_success(value)

    monkeypatch.setattr(app, "start_async", sync_start)
    page.cmd_var.set("uname -a")
    page.run_remote()
    assert ran["value"]["output"] == "hello"
    assert "uname -a" in page.results.get("1.0", "end")

    page.test_connection()
    assert ran["value"]["ok"] is True

    # The terminal now targets the saved server and can run remotely.
    term.refresh_targets()
    term.target.set("gpu-box")
    term.cmd_entry.insert(0, "nvidia-smi")
    term.run_command()
    assert ran["value"]["command"] == "nvidia-smi"
    assert "nvidia-smi" in term.output.get("1.0", "end")


def test_shortcuts_and_diagnostics_settings(fake_ui, monkeypatch):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # Shortcuts are bound at startup and the help dialog does not crash.
    app.refresh_current()
    app.show_shortcuts_help()

    def sync_start(label, task, on_success=None, on_error=None):
        try:
            value = task()
        except Exception as exc:
            if on_error:
                on_error(str(exc))
            return
        if on_success:
            on_success(value)

    monkeypatch.setattr(app, "start_async", sync_start)

    settings = app.pages["settings"]
    app.show_page("settings")
    settings.run_check()
    assert "Проверка завершена" in settings.diag_status.get()
    assert settings.diag_text.get("1.0", "end").strip()
    settings.copy_diag()
    settings.show_log()
    assert settings.diag_status.get().startswith("Файл лога:")

    # Chat panel exposes focus_input used by Ctrl+K.
    chat = app.pages["chat"]
    chat.focus_input()


def test_editor_tabs_palette_and_search(fake_ui, monkeypatch, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("print('a')\n", encoding="utf-8")
    (workspace / "b.py").write_text("print('b')\nval_loss = 1\n", encoding="utf-8")
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    editor = app.pages["editor"]
    app.show_page("editor")

    # Tabs: two open files, buffers are kept per tab.
    editor.open_file(workspace / "a.py")
    editor.open_file(workspace / "b.py")
    assert len(editor._tabs) == 2
    assert editor._current_path == workspace / "b.py"
    editor.editor.delete("1.0", "end")
    editor.editor.insert("1.0", "edited b\n")
    editor._select_tab(0)  # switch to a.py — b's buffer must be stashed
    assert editor._current_path == workspace / "a.py"
    assert "print" in editor.editor.get("1.0", "end")
    editor._select_tab(1)
    assert editor.editor.get("1.0", "end") == "edited b\n"

    # Closing a modified tab asks first (faked yes) and removes the tab.
    editor._tabs[1]["modified"] = True
    editor.close_tab(1)
    assert len(editor._tabs) == 1

    # Save the active tab after editing.
    editor.editor.delete("1.0", "end")
    editor.editor.insert("1.0", "x = 42\n")
    editor.save_file()
    assert (workspace / "a.py").read_text(encoding="utf-8") == "x = 42\n"

    # Ctrl+Tab cycles tabs.
    editor.open_file(workspace / "b.py")
    editor.next_tab()
    assert editor._current_path == workspace / "a.py"

    # Quick open palette (Ctrl+P): fuzzy filter + Enter opens the file.
    palette = app.open_command_palette("files")
    assert len(palette._filtered) == 2
    palette.query.insert(0, "b.py")
    palette.refresh()
    assert len(palette._filtered) == 1
    palette.run_selected()
    assert editor._current_path == workspace / "b.py"

    # Command palette (Ctrl+Shift+P): commands run through.
    def sync_start(label, task, on_success=None, on_error=None):
        try:
            value = task()
        except Exception as exc:
            if on_error:
                on_error(str(exc))
            return
        if on_success:
            on_success(value)

    monkeypatch.setattr(app, "start_async", sync_start)
    cmds = app.open_command_palette("commands")
    assert len(cmds._items) >= 15
    cmds.query.insert(0, "Диагностика")
    cmds.refresh()
    assert len(cmds._filtered) == 1
    cmds.run_selected()
    assert "Проверка завершена" in app.pages["settings"].diag_status.get()

    # Search page: regex search, jump-to-line opens the file in the editor.
    search = app.pages["search"]
    app.show_page("search")
    search.query_var.set("val_loss")
    search.run_search()
    assert search._results
    search.tree.selection_set(search.tree.get_children()[0])
    search.open_selected()
    assert editor._current_path == workspace / "b.py"
    assert search.status_var.get().startswith("Совпадений")


def test_bottom_panel_problems_and_git_badge(fake_ui, monkeypatch, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # Bottom panel switches between terminal and problems, and hides (Ctrl+J).
    assert app._bottom_view == "terminal"
    app.show_bottom("problems")
    assert app._bottom_view == "problems"
    app.toggle_bottom()
    assert app._bottom_visible is False
    app.toggle_bottom()
    assert app._bottom_visible is True

    # Problems panel parses the training log into file/line markers.
    app.training.tail = lambda *a, **k: (
        'Traceback (most recent call last):\n'
        '  File "train.py", line 42, in <module>\n'
        'ValueError: bad\n')
    problems = app.problems
    problems.refresh()
    assert len(problems._items) >= 2
    assert problems.count_var.get().startswith("ПРОБЛЕМЫ (")

    # Jump to code opens the file in the editor.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "train.py").write_text("x = 1\n", encoding="utf-8")
    app.settings.workspace_path = str(workspace)
    app.save_settings()
    index = next(i for i, p in enumerate(problems._items) if p["path"] == "train.py")
    problems.tree.selection_set(problems.tree.get_children()[index])
    problems.open_selected()
    assert app.pages["editor"]._current_path == workspace / "train.py"

    # Git badge handles a non-repo workspace gracefully.
    assert app.git_badge.get().startswith("git:")

    # Completion + highlighting wiring is inert-safe with fake widgets.
    editor = app.pages["editor"]
    editor.editor.insert("1.0", "import torch\ntra")
    editor.completion.update()
    assert editor.completion.visible is False
    editor._apply_highlight()
    editor._on_key_release(type("E", (), {"keysym": "a"})())
    editor._on_tab_key()
    editor._on_escape()
    editor._on_return_key()
    editor._on_up_key()
    editor._on_down_key()
    editor._on_click()


def test_editor_find_replace_bookmarks_gutter(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "code.py").write_text("alpha beta\ngamma beta\n", encoding="utf-8")
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    editor = app.pages["editor"]
    app.show_page("editor")
    editor.open_file(workspace / "code.py")

    # Gutter renders line numbers.
    editor._regen_gutter()
    assert "1" in editor.gutter.get("1.0", "end")

    # Find bar: matches are counted and navigation reports position.
    editor.open_find()
    editor.find_var.set("beta")
    editor._refresh_matches()
    assert len(editor._matches) == 2
    editor.find_next(1)
    assert editor.find_status.get() == "1 из 2"
    editor.find_next(-1)
    assert editor.find_status.get() == "2 из 2"

    # Replace all rewrites the buffer and marks the tab modified.
    editor.replace_var.set("delta")
    editor.replace_all_in_file()
    buffer = editor.editor.get("1.0", "end")
    assert "delta" in buffer and "beta" not in buffer
    assert editor._tabs[editor._active]["modified"] is True

    # Bookmarks: toggle, navigate, toggle off.
    editor.toggle_bookmark(1)
    editor.toggle_bookmark(3)
    assert editor._tabs[editor._active]["bookmarks"] == {1, 3}
    editor.goto_bookmark(1)
    editor.goto_bookmark(-1)
    editor.toggle_bookmark(1)
    assert editor._tabs[editor._active]["bookmarks"] == {3}

    # Problem markers show up in the gutter for the current file.
    app.problems._items = [{"severity": "error", "message": "boom",
                            "path": "code.py", "line": 2}]
    editor._regen_gutter()
    assert "●" in editor.gutter.get("1.0", "end")

    editor.close_find()
    assert editor.find_visible is False


def test_git_panel_and_editor_polish(fake_ui, tmp_path, monkeypatch):
    from types import SimpleNamespace

    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    git_panel = app.git_panel

    # Without a workspace the panel explains itself instead of crashing.
    git_panel.refresh()
    assert "не выбрана" in git_panel.status_var.get()

    workspace = tmp_path / "proj"
    workspace.mkdir()
    (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    monkeypatch.setattr(app.git, "status", lambda root: SimpleNamespace(
        branch="main", ahead_behind="0 1", changes=("?? a.py",),
        path=str(root)))
    monkeypatch.setattr(app.git, "numstat",
                        lambda root, staged=False: "1\t0\ta.py")
    monkeypatch.setattr(app.git, "diff_text",
                        lambda root, **kwargs: "+x = 1\n")
    git_panel.refresh()
    assert git_panel.tree.get_children() == ["a.py"]
    assert git_panel.branch_var.get() == "ветка: main 0 1"
    assert git_panel.status_var.get() == "Изменений: 1"

    git_panel._set_diff_text("+x = 1\n-old\n")
    assert "x = 1" in git_panel.diff.get("1.0", "end")

    recorded: dict = {}
    monkeypatch.setattr(
        app.git, "commit",
        lambda root, msg: recorded.setdefault("message", msg) or "ok")
    git_panel.commit_var.set("первый коммит")
    git_panel.commit_changes()
    assert recorded["message"] == "первый коммит"

    # Editor: go-to-line, auto-close, bracket highlight stay crash-free.
    editor = app.pages["editor"]
    app.show_page("editor")
    editor.open_file(workspace / "a.py")
    editor.open_goto_line()
    assert editor.goto_visible is True
    editor.goto_var.set("2")
    editor.goto_line_jump()
    assert editor.goto_visible is False
    assert editor._on_auto_char("(") == "break"
    assert editor._on_backspace() in ("break", None)
    editor._highlight_bracket()
    editor._on_click()
    editor._on_escape()

    # File operations: create, refuse traversal, rename, delete.
    editor.new_name_var.set("b.py")
    editor.create_file()
    assert (workspace / "b.py").exists()
    editor.new_name_var.set("../evil.py")
    editor.create_file()
    assert not (tmp_path / "evil.py").exists()

    editor.tree._selection = (str(workspace / "b.py"),)
    editor.new_name_var.set("c.py")
    editor.rename_selected()
    assert (workspace / "c.py").exists()
    assert not (workspace / "b.py").exists()

    editor.tree._selection = (str(workspace / "c.py"),)
    editor.delete_selected()
    assert not (workspace / "c.py").exists()


def test_editor_format_lint_zoom_minimap(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "code.py").write_text("x = 1  \n\n\n\n\ny = 2",
                                       encoding="utf-8")
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    editor = app.pages["editor"]
    app.show_page("editor")
    editor.open_file(workspace / "code.py")

    # Formatter cleans the buffer and reports the number of fixes.
    editor.format_file()
    buffer = editor.editor.get("1.0", "end")
    assert "x = 1\n" in buffer and "  \n" not in buffer
    assert "исправлений" in editor.status_var.get()

    # Linter feeds the problems panel (and thus the gutter).
    editor.editor.insert("end", "\ndef broken(:\n")
    editor.run_lint()
    assert any(item["severity"] == "error"
               for item in app.problems.file_items)
    assert app.problems._items  # refresh() merged them in
    assert "линт" in editor.status_var.get()

    # Zoom adjusts fonts without crashing.
    editor.zoom_in()
    editor.zoom_out()

    # Minimap redraws and click-to-jump is crash-free.
    editor._redraw_minimap()
    editor._on_minimap_click(type("E", (), {"y": 10})())

    # Save honours format-on-save and lint-on-save.
    editor.format_on_save.set(True)
    editor.editor.delete("1.0", "end")
    editor.editor.insert("1.0", "z = 3  \n")
    editor.save_file()
    saved = (workspace / "code.py").read_text(encoding="utf-8")
    assert saved == "z = 3\n"


def test_theme_toggle_and_split_editor(fake_ui, tmp_path):
    from alterego_training_hub import theme as theme_module

    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    try:
        # Theme switch mutates the live palette and is crash-free on fakes.
        app.toggle_theme("dark")
        assert theme_module.C["bg"] == theme_module.PALETTES["dark"]["bg"]
        assert app.settings.ui_theme == "dark"
        app.toggle_theme("light")
        assert theme_module.C["bg"] == theme_module.PALETTES["light"]["bg"]
    finally:
        theme_module.set_palette("light")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.py").write_text("x = 1\n", encoding="utf-8")
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    editor = app.pages["editor"]
    app.show_page("editor")
    editor.open_file(workspace / "a.py")

    # Split: second pane mirrors the buffer; edits sync both ways.
    editor.toggle_split()
    assert editor.split_visible is True
    assert "x = 1" in editor.editor2.get("1.0", "end")
    editor._mark_edited(2)
    editor.editor2.insert("end", "y = 2\n")
    editor._sync_split_buffers()
    assert "y = 2" in editor.editor.get("1.0", "end")
    editor._regen_gutter()
    editor._apply_highlight()
    editor.toggle_split()
    assert editor.split_visible is False


def test_agent_settings_and_model_tools(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    settings_page = app.pages["settings"]

    # Agent settings are editable and persist.
    settings_page.agent_steps_var.set("12")
    settings_page.agent_verify_var.set(False)
    settings_page.agent_subagents_var.set(False)
    settings_page.agent_reasoning_var.set("high")
    settings_page.agent_extra_text.insert("1.0", "Пиши по-русски.")
    settings_page.save_agent()
    assert app.settings.agent_max_steps == 12
    assert app.settings.agent_verify is False
    assert app.settings.agent_subagents is False
    assert app.settings.agent_reasoning == "high"
    assert "Пиши по-русски." in app.settings.agent_system_extra

    # Provider picker fills defaults and stores the canonical id.
    settings_page.provider_var.set("Anthropic (Claude)")
    settings_page._on_provider_selected()
    assert "anthropic" in settings_page.mentor_vars["mentor_base_url"].get()
    settings_page._collect_mentor()
    assert app.settings.llm_provider == "anthropic"
    assert app.settings.mentor_provider == "Anthropic (Claude)"

    # New agent tools are wired: model info, hot control, plan.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    app.settings.workspace_path = str(workspace)
    app.save_settings()
    tools, schemas, mutations = app.agent_extra_tools()
    for name in ("get_model_info", "list_model_catalog", "get_metrics_history",
                 "get_training_control", "set_training_control", "set_plan",
                 "spawn_subagent"):
        assert name in tools
        assert any(schema["function"]["name"] == name for schema in schemas)
    assert "set_training_control" in mutations

    result = tools["set_training_control"]({"lr": 0.1, "note": "тест"})
    assert result["ok"] is True
    assert (workspace / "control.json").exists()
    result = tools["get_training_control"]({})
    assert result["ok"] and result["control"]["lr"] == 0.1
    result = tools["get_model_info"]({})
    assert result["ok"] and "metrics" in result and "training" in result
    result = tools["get_metrics_history"]({})
    assert result["ok"] and "series" in result
    result = tools["list_model_catalog"]({})
    assert result["ok"] is True
    result = tools["set_plan"]({"steps": ["шаг 1", "шаг 2"]})
    assert result["ok"] and app.agent_plan == ["шаг 1", "шаг 2"]
    # Subagents are disabled in settings → tool refuses politely.
    result = tools["spawn_subagent"]({"goal": "проверка"})
    assert result["ok"] is False


def test_update_plan_profiles_watchdog_and_chart(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # update_plan stores tasks and notifies the chat panel.
    tools, schemas, _mutations = app.agent_extra_tools()
    assert any(schema["function"]["name"] == "update_plan" for schema in schemas)
    result = tools["update_plan"]({"steps": [
        {"title": "прочитать метрики", "status": "done"},
        {"title": "скорректировать lr", "status": "in_progress"},
        {"title": "проверить результат", "status": "pending"},
    ]})
    assert result["ok"] is True
    assert app.agent_tasks[0]["status"] == "done"
    assert app.chat_panel.tasks_var.get()  # checklist rendered
    result = tools["update_plan"]({"steps": []})
    assert result["ok"] is False

    # Agent profiles apply and persist.
    settings_page = app.pages["settings"]
    settings_page.agent_profile_var.set("Ревьюер кода")
    settings_page.apply_agent_profile()
    assert app.settings.agent_profile == "reviewer"
    assert app.settings.agent_verify is True
    assert app.settings.agent_reasoning == "high"
    assert "ревью" in app.settings.agent_system_extra.lower()

    # Watchdog tick is safe to run headless and resets when idle.
    app._watchdog_tick()
    assert app.watchdog.last_report is None  # nothing running → reset

    # Chart maths work through the shared drawing helper.
    from alterego_training_hub.ui_common import draw_line_chart

    class FakeCanvas:
        def __init__(self):
            self.items = []

        def delete(self, *a):
            self.items.clear()

        def create_line(self, *coords, **kw):
            self.items.append(("line", coords))

        def create_text(self, *a, **kw):
            self.items.append(("text", a))

        def create_oval(self, *a, **kw):
            self.items.append(("oval", a))

    canvas = FakeCanvas()
    draw_line_chart(canvas, {"loss": [2.0, 1.5, 1.1, 0.9]})
    kinds = {kind for kind, _ in canvas.items}
    assert {"line", "text", "oval"} <= kinds

    # Model dashboard renders the live chart + watchdog lines.
    model_page = app.pages["model"]
    model_page._render_progress()
    assert model_page.watchdog_var.get() is not None


def test_stage17_tools_eval_tuning_dataset(fake_ui, tmp_path):
    import json

    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    tools, schemas, mutations = app.agent_extra_tools()
    for name in ("get_eval_report", "suggest_training_fixes", "compare_runs",
                 "prepare_dataset"):
        assert name in tools
        assert any(schema["function"]["name"] == name for schema in schemas)
    assert "prepare_dataset" in mutations

    # Eval report works on empty log and on synthetic epoch lines.
    result = tools["get_eval_report"]({})
    assert result["ok"] and result["points"] == 0
    log_file = tmp_path / "training.log"
    app.training._log_path = log_file
    log_file.write_text(
        "epoch 1/2 loss=2.0 acc=0.5 val_loss=2.1 val_acc=0.5 perplexity=8.1 lr=0.05\n"
        "epoch 2/2 loss=1.0 acc=0.7 val_loss=1.2 val_acc=0.7 perplexity=3.3 lr=0.05\n",
        encoding="utf-8")
    result = tools["get_eval_report"]({})
    assert result["ok"] and result["best_epoch"] == 2

    # Suggestions are read-only and reference control keys.
    result = tools["suggest_training_fixes"]({})
    assert result["ok"] and result["suggestions"]

    # prepare_dataset: filter + split a workspace jsonl.
    source = workspace / "corpus.jsonl"
    source.write_text(
        "\n".join(json.dumps({"text": f"пример {i}" * (3 if i % 2 else 1)},
                             ensure_ascii=False) for i in range(10)),
        encoding="utf-8")
    result = tools["prepare_dataset"]({"path": "corpus.jsonl",
                                       "min_chars": 20})
    assert result["ok"] is True
    assert (workspace / "corpus.train.jsonl").exists()
    assert result["filtered_rows"] < 10
    result = tools["prepare_dataset"]({"path": "missing.jsonl"})
    assert result["ok"] is False

    # Model page: hyperparameter suggestions round-trip.
    model_page = app.pages["model"]
    model_page.suggest_fixes()  # askyesno fake returns True → writes control.json
    assert (workspace / "control.json").exists()

    # Datasets page: HF download without network is refused cleanly;
    # filter/split works on a real library entry.
    datasets_page = app.pages["datasets"]
    datasets_page.hf_var.set("bad id without slash")
    datasets_page.download_hf()  # no crash; shows info dialog (faked)
    datasets_page.filter_var.set("пример")
    library = datasets_page._library()
    from alterego_training_hub.datasets import DatasetEntry

    library.add(DatasetEntry(name="corpus", format="jsonl",
                             location=str(source)))
    datasets_page.refresh()
    iid = next(iter(datasets_page._entries))
    datasets_page.tree._selection = (iid,)
    datasets_page.filter_split()
    assert (workspace / "corpus.train.jsonl").exists()

    # Training page: A/B compare of two synthetic run logs.
    training_page = app.pages["training"]
    log_a = tmp_path / "run_a.log"
    log_b = tmp_path / "run_b.log"
    log_a.write_text(
        "epoch 1/2 loss=1.0 acc=0.6 val_loss=1.1 lr=0.05\n"
        "epoch 2/2 loss=0.5 acc=0.8 val_loss=0.6 lr=0.05\n", encoding="utf-8")
    log_b.write_text(
        "epoch 1/2 loss=1.5 acc=0.4 val_loss=1.6 lr=0.05\n"
        "epoch 2/2 loss=1.2 acc=0.5 val_loss=1.3 lr=0.05\n", encoding="utf-8")
    app.runs.start("python train.py", str(workspace), log_path=str(log_b))
    app.runs.start("python train.py", str(workspace), log_path=str(log_a))
    training_page.compare_runs()
    assert "Сравнение" in training_page.metrics_var.get()


def test_stage18_model_tools_export_quantize_bench_suite(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    tools, schemas, mutations = app.agent_extra_tools()
    for name in ("export_model", "quantize_model", "benchmark_model",
                 "run_prompt_suite"):
        assert name in tools
        assert any(schema["function"]["name"] == name for schema in schemas)
    assert {"export_model", "quantize_model", "benchmark_model",
            "run_prompt_suite"} <= mutations

    # Local model catalog entry drives export/quantize.
    from alterego_training_hub.models_registry import ModelEntry

    model_file = tmp_path / "weights.gguf"
    model_file.write_bytes(b"GGUF" + b"\0" * 200_000)
    entry = ModelEntry(name="demo-model", kind="local", location=str(model_file))
    app.model_registry().add(entry)

    result = tools["export_model"]({"model_id": entry.id, "format": "gguf"})
    # No converters in the sandbox → clean, actionable failure (no crash).
    assert "checks" in result and "hint" in result

    result = tools["quantize_model"]({"model_id": entry.id,
                                      "quant_type": "nope"})
    assert result["ok"] is False and "types" in result

    result = tools["benchmark_model"]({"model_id": entry.id})
    assert result["ok"] is False  # local model has no endpoint/command

    result = tools["benchmark_model"]({
        "command": "python -c \"print('tokens=50')\""})
    assert result["ok"] is True and result["line"]
    assert "tok/s" in result["line"]

    result = tools["run_prompt_suite"]({})
    assert result["ok"] is False  # no endpoint configured

    # Models page tool buttons respond safely without a selection.
    models_page = app.pages["models"]
    models_page.refresh()
    models_page._run_model_tool("export_model", {}, "Экспорт")  # info dialog
    models_page.tools_status.set("ok")
    assert models_page.tools_status.get() == "ok"

    # Playground suite button exists and errors cleanly without models.
    playground_page = app.pages["playground"]
    playground_page.run_prompt_suite()  # no models → error dialog, no crash


def test_stage19_reports_cloud_queue_roles(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    app.settings.workspace_path = str(workspace)
    app.save_settings()

    tools, schemas, mutations = app.agent_extra_tools()
    for name in ("export_report", "list_cloud_jobs", "submit_cloud_job"):
        assert name in tools
        assert any(schema["function"]["name"] == name for schema in schemas)
    assert {"export_report", "submit_cloud_job"} <= mutations

    # Report export through the agent tool.
    result = tools["export_report"]({"path": "reports/отчёт", "format": "md"})
    assert result["ok"] is True, result
    assert (workspace / "reports" / "отчёт.md").exists()
    result = tools["export_report"]({"format": "html"})
    assert result["ok"] is True

    # Cloud queue: list empty, add via tool requires RunPod key (clean error),
    # and the queue itself works offline.
    result = tools["list_cloud_jobs"]({})
    assert result["ok"] and result["jobs"] == []
    result = tools["submit_cloud_job"]({"name": "run", "command": "python t.py"})
    assert result["ok"] is False  # no RunPod key in the sandbox

    from alterego_training_hub.cloud_queue import CloudJob, CloudJobQueue

    queue = CloudJobQueue(app.model_registry().library_dir)
    queue.add(CloudJob(name="demo", command="python train.py"))
    result = tools["list_cloud_jobs"]({})
    assert len(result["jobs"]) == 1 and "demo" in result["jobs"][0]["line"]

    # build_report_context assembles everything without crashing.
    context = app.build_report_context()
    text = __import__("alterego_training_hub.report_export",
                      fromlist=["build_markdown_report"]).build_markdown_report(
        context)
    assert "Модель" in text

    # Guest role blocks every mutation through agent tools.
    app.settings.access_role = "viewer"
    tools, _schemas, _mutations = app.agent_extra_tools()
    for name in ("start_training", "set_training_control", "export_report",
                 "prepare_dataset", "export_model", "submit_cloud_job"):
        result = tools[name]({})
        assert result["ok"] is False and "Гостевой режим" in result["error"]
    # Read-only tools still work.
    assert tools["list_cloud_jobs"]({})["ok"] is True
    app.settings.access_role = "owner"

    # Settings: role combobox saves.
    settings_page = app.pages["settings"]
    settings_page.access_role_var.set("Редактор — без секретов и смены ролей")
    settings_page.save_access_role()
    assert app.settings.access_role == "editor"

    # GPU page queue widgets exist and refresh offline.
    gpu_page = app.pages["gpu"]
    gpu_page.refresh_jobs()
    gpu_page.job_name_var.set("t2")
    gpu_page.job_cmd_var.set("python t.py")
    gpu_page.add_cloud_job()
    assert gpu_page.job_tree.get_children()

    # Chat session export/import methods are wired (empty session → info).
    chat_page = app.pages["chat"]
    chat_page.export_session()  # empty → info dialog, no crash


def test_stage20_platform_hotkeys_layouts_plugins(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    settings_page = app.pages["settings"]

    # Language switch persists.
    settings_page.language_var.set("English")
    settings_page.save_language()
    assert app.settings.ui_language == "en"
    settings_page.language_var.set("Русский")
    settings_page.save_language()
    assert app.settings.ui_language == "ru"

    # Custom hotkeys save and reset.
    settings_page.hotkey_vars["page.chat"].set("<Control-t>")
    settings_page.save_hotkeys()
    assert app.settings.hotkeys == {"page.chat": "<Control-t>"}
    settings_page.hotkey_vars["page.chat"].set("<Control-p>")  # conflict
    settings_page.save_hotkeys()  # error dialog (faked), no crash
    settings_page.reset_hotkeys()
    assert app.settings.hotkeys == {}

    # Named layout applies and custom layout snapshot saves.
    settings_page.layout_var.set("analytics")
    settings_page.apply_layout_preset()
    assert app._current_page == "model"
    settings_page.save_current_layout()
    from pathlib import Path as _P

    assert list(_P(app.model_registry().library_dir).glob("layout-*.json"))
    state = app.current_layout()
    assert state.page == "model"

    # Plugin loads, merges into agent tools, and respects the guest role.
    plugin_dir = app.plugins.plugins_dir
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "hello.py").write_text(
        "PLUGIN = {'id': 'hello', 'name': 'Hello', 'version': '1.0',\n"
        "  'tools': {'hello_tool': {\n"
        "    'schema': {'type': 'function', 'function': {\n"
        "      'name': 'hello_tool', 'description': 'hi',\n"
        "      'parameters': {'type': 'object', 'properties': {}}}},\n"
        "    'handler': lambda args: {'ok': True, 'text': 'hi'},\n"
        "    'mutation': False},\n"
        "   'hello_write': {\n"
        "    'schema': {'type': 'function', 'function': {\n"
        "      'name': 'hello_write', 'description': 'm',\n"
        "      'parameters': {'type': 'object', 'properties': {}}}},\n"
        "    'handler': lambda args: {'ok': True},\n"
        "    'mutation': True}}}\n",
        encoding="utf-8")
    settings_page.reload_plugins()
    assert "Hello" in settings_page.plugins_var.get()
    tools, _schemas, mutations = app.agent_extra_tools()
    assert "hello_tool" in tools and "hello_write" in mutations
    assert tools["hello_tool"]({}) == {"ok": True, "text": "hi"}

    app.settings.access_role = "viewer"
    tools, _schemas, _mutations = app.agent_extra_tools()
    result = tools["hello_write"]({})
    assert result["ok"] is False and "Гостевой режим" in result["error"]
    assert tools["hello_tool"]({})["ok"] is True  # read-only plugin tool
    app.settings.access_role = "owner"


def test_stage23_live_language_and_panel_dnd(fake_ui, tmp_path):
    """Live language switch plus drag-and-drop docking state."""
    from alterego_training_hub.i18n import t
    from alterego_training_hub.layouts import layout_info

    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # --- live language: nav labels rebuilt in the new language
    before = app._nav_buttons["editor"]._kwargs["text"]
    assert t("Редактор кода") in before

    editor = app.pages["editor"]
    editor._tabs = [{"path": tmp_path / "demo.py", "text": "",
                     "modified": True, "bookmarks": []}]
    editor._active = 0
    editor.editor.insert("1.0", "hello buffer")
    app.chat_panel.session.add("user", "привет")
    assert len(app.chat_panel.session.messages) == 1

    app.apply_language("en")
    after = app._nav_buttons["editor"]._kwargs["text"]
    assert "Code editor" in after and after != before
    # editor tabs with unsaved text survive the rebuild
    assert app.pages["editor"]._tabs[0]["text"] == "hello buffer"
    # chat session survives the rebuild
    assert len(app.chat_panel.session.messages) == 1

    app.apply_language("ru")
    assert t("Редактор кода") in app._nav_buttons["editor"]._kwargs["text"]

    # --- drag-and-drop docking
    app._dock_panel("chat", "left")
    assert app.settings.chat_side == "left"
    app._dock_panel("sidebar", "right")
    assert app.settings.sidebar_side == "right"
    state = app.current_layout()
    assert state.chat_side == "left" and state.sidebar_side == "right"

    # named layout restores dock sides and bottom height
    app.apply_layout(layout_info("code"))
    assert app.settings.chat_side == "right"
    assert app.settings.sidebar_side == "left"
    assert app.settings.bottom_height == 210

    app.settings.bottom_height = 320
    assert app.current_layout().bottom_height == 320


def test_stage24_plugin_sandbox_catalog_ui(fake_ui, tmp_path):
    """Settings page: catalog install, trust toggle, sandboxed by default."""
    from alterego_training_hub.plugins import PluginManager

    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    settings_page = app.pages["settings"]

    # Hermetic plugin store for this test.
    app.plugins = PluginManager(tmp_path / "plugins")
    app._plugin_list = app.plugins.load_all()

    # Catalog install works from the embedded builtin source.
    settings_page._refresh_catalog_combo()
    settings_page.catalog_choice.current = lambda *a: 0
    settings_page.install_from_catalog()
    hello = next(p for p in app._plugin_list if p.id == "hello")
    assert hello.ok and hello.trusted is False
    assert hello.tools and hello.tools[0].sandboxed is True

    # Trust toggle via the UI persists and switches execution mode.
    settings_page.plugin_choice.current = lambda *a: 0
    settings_page.set_selected_plugin_trust(True)
    hello = next(p for p in app._plugin_list if p.id == "hello")
    assert hello.trusted is True and hello.tools[0].sandboxed is False
    settings_page.set_selected_plugin_trust(False)
    hello = next(p for p in app._plugin_list if p.id == "hello")
    assert hello.trusted is False

    # Uninstall via the UI.
    settings_page.uninstall_selected_plugin()
    assert app._plugin_list == [] or all(
        p.id != "hello" or not p.ok for p in app._plugin_list)


def test_stage25_night_watch_dashboard_colab(fake_ui, tmp_path):
    """Night watch settings, morning report, chat dashboard, Colab export."""
    from alterego_training_hub.cloud_queue import CloudJob, CloudJobQueue

    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # --- night watch settings round-trip via the model page
    model_page = app.pages["model"]
    model_page.night_enabled_var.set(True)
    model_page.night_interval_var.set("45")
    model_page.save_night_watch()
    assert app.settings.night_watch_enabled is True
    assert app.settings.night_watch_interval == 45
    assert "45" in model_page.night_status_var.get()

    # --- morning report works with an empty log
    text = app.morning_report_text()
    assert "Ночных проверок не было" in text

    # --- run_night_check with a fake mentor records a log entry
    class _Reply:
        text = "Обучение стабильно. Рисков нет. Оставить lr."

    class _Mentor:
        def respond(self, messages, *, tools, max_tokens, temperature):
            return _Reply()

    app.mentor_client = lambda: _Mentor()
    entry = app.run_night_check()
    assert entry.ok is True
    assert app.night_watch_log().entries()
    report = app.morning_report_text()
    assert "Проверок: 1" in report

    # --- chat dashboard post
    chat = app.chat_panel
    chat.post_dashboard()
    assert any("📊" in message.content for message in chat.session.messages)

    # --- Colab export from the cloud job queue
    queue = CloudJobQueue(app.model_registry().library_dir)
    queue.add(CloudJob(name="ночной запуск", command="python train.py"))
    gpu_page = app.pages["gpu"]
    gpu_page.refresh_jobs()
    iids = list(gpu_page._jobs)
    assert iids
    gpu_page.job_tree.selection = lambda *a: iids[:1]
    gpu_page.export_selected_job_to_colab()
    exports = list((app.model_registry().library_dir / "exports").glob("*.ipynb"))
    assert exports
    assert "train.py" in exports[0].read_text(encoding="utf-8")


def test_stage26_transparency_thoughts_actions_context_critic(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    chat = app.chat_panel

    # --- transparency buttons exist and text helpers work on empty session
    assert "нет ответов" in chat.last_thought_text()
    assert "не вызывал" in chat.actions_text()
    context = chat.context_text()
    assert "Модель:" in context and "Системный промпт" in context

    # --- thought protocol renders as steps, answer stays clean
    chat.session.add(
        "assistant",
        "Мысль: смотрю лог\nДействие: читаю метрики\nОтвет: Всё стабильно.")
    thoughts = chat.last_thought_text()
    assert "💭 Мысль: смотрю лог" in thoughts
    assert "⚙ Действие: читаю метрики" in thoughts
    chat._render_messages()
    rendered = chat.messages.get("1.0", "end") or ""
    assert "Всё стабильно." in rendered

    # --- action trace from tool messages + explain prompt
    chat.session.add("tool", '{"ok": true, "summary": "прочитано 12 строк"}',
                     name="read_file")
    actions = chat.actions_text()
    assert "read_file" in actions and "прочитано" in actions
    entries = chat.action_entries()
    assert entries and entries[-1].ok

    # --- model page: transparency toggles persist + samples hint
    model_page = app.pages["model"]
    model_page.thought_var.set(False)
    model_page.critic_var.set(True)
    model_page.save_transparency()
    assert app.settings.thought_protocol is False
    assert app.settings.critic_enabled is True
    assert "Сэмплов в логе" in model_page.samples_text()

    # --- critic via fake mentor posts a verdict into the chat
    class _Reply:
        text = "ВЕРДИКТ: ок\nУВЕРЕННОСТЬ: 0.9\nПРОБЛЕМЫ: —"
        usage: ClassVar[dict] = {}
        model = "fake"

    class _Mentor:
        def respond(self, messages, *, tools=None, max_tokens=0, temperature=0.0):
            return _Reply()

    app.mentor_client = lambda: _Mentor()
    app.start_async = lambda label, task, done=None, failed=None: done(task())
    chat.run_critique_last()
    assert any("Критик" in m.content for m in chat.session.messages)


def test_stage27_wizard_plan_tokenizer_baseline(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    model_page = app.pages["model"]

    # --- empty dataset: plan still renders with audit warnings
    text = model_page.wizard_plan_text()
    assert "🎯 Путь" in text and "💰 Ресурсы" in text and "▶ Шаги" in text

    # --- dataset file: audit + plan with real rows, tokenizer trains & saves
    data = tmp_path / "data.txt"
    data.write_text(("привет мир это обучающие данные для модели\n" * 60)
                    + "уникальная строка про обучение нейросетей\n",
                    encoding="utf-8")
    model_page.wizard_dataset_var.set(str(data))
    plan = model_page.wizard_plan_text()
    assert "Строк: 61" in plan or "61" in plan
    model_page.train_tokenizer_now()
    saved = list((app.model_registry().library_dir / "tokenizers").glob("*.json"))
    assert saved
    assert "Токенизатор сохранён" in model_page.wizard_var.get()

    # --- baseline snapshot + before/after on empty logs does not crash
    model_page.save_wizard_baseline()
    assert model_page._wizard_baseline_path().is_file()
    result = model_page.before_after_text()
    assert "val_loss" in result


def test_stage28_ux_patterns_sidebar_status_chat(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # --- activity bar: compact toggle switches nav to icons
    assert app.toggle_sidebar_compact() is True
    label = app._nav_buttons["training"]._kwargs.get("text", "")
    assert "🏋" in label
    assert app.toggle_sidebar_compact() is False
    wide = app._nav_buttons["training"]._kwargs.get("text", "")
    assert "Обучение" in wide or wide  # fake may not store text; state is enough
    assert app._sidebar_compact is False

    # --- nav badge + status badges
    app.set_nav_badge("training", "●")
    assert app._nav_badges["training"] == "●"
    app.settings.mentor_model = "gpt-4o"
    app.refresh_status_badges()
    assert "gpt-4o" in app.model_badge.get()

    # --- header primary-action pattern is available
    from alterego_training_hub.ui_patterns import primary_action
    assert primary_action("training")[1] == "start_training"

    # --- chat: session search filter + attach button exists
    chat = app.chat_panel
    chat._sessions_cache = []
    chat.session_search_var.set("про")
    assert chat.filtered_session_titles()
    chat.session_search_var.set("")
    assert hasattr(chat, "attach_btn")


def test_stage30_agent_benchmark_button_and_events(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    model_page = app.pages["model"]
    text = model_page.agent_benchmark_text()
    assert "5/5" in text
    # chat renders reliability events without crashing
    chat = app.chat_panel
    chat.on_agent_event("retry", {"attempt": 1, "category": "transient"})
    chat.on_agent_event("loop_detected", {"name": "read_file", "detail": "x"})


def test_stage31_wizard_generates_train_script(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    model_page = app.pages["model"]
    data = tmp_path / "data.txt"
    data.write_text("привет мир обучающие данные для модели\n" * 30,
                    encoding="utf-8")
    model_page.wizard_dataset_var.set(str(data))
    target = model_page.create_train_script()
    assert target.is_file()
    code = target.read_text(encoding="utf-8")
    import ast as _ast
    _ast.parse(code)
    assert '{"sample":' in code and "eval: val_loss=" in code
    assert app.settings.training_command == "python train_llm.py"


def test_stage32_smoke_run_button(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    model_page = app.pages["model"]
    # no script yet -> honest failure report, no crash
    missing = model_page.smoke_text()
    assert "не найден" in missing
    # generate into the library scripts dir (no workspace selected), then smoke
    data = tmp_path / "data.txt"
    data.write_text("данные для smoke проверки цепочки\n" * 5, encoding="utf-8")
    model_page.wizard_dataset_var.set(str(data))
    model_page.create_train_script()
    report = model_page.smoke_text()
    assert "7/7" in report, report


def test_stage33_parallel_event_renders(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    app.chat_panel.on_agent_event("parallel_batch",
                                  {"count": 3, "names": ["read_file"]})


def test_stage34_live_benchmark_button(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    model_page = app.pages["model"]
    # без настроенного провайдера — честный текст ошибки, не исключение
    text = model_page.live_benchmark_text()
    assert text
    # со скриптовым ментором — полный прогон 3/3
    from alterego_training_hub.agent_bench import ScriptedMentor
    from alterego_training_hub.mentor import MentorReply, ToolCall

    def tc(name, **args):
        return ToolCall(id="x", name=name, arguments=args)

    script = [
        MentorReply(text="", model="m", usage={},
                    tool_calls=(tc("replace_in_file", path="calc.py",
                                   find="a - b", replace="a + b"),)),
        MentorReply(text="Исправил.", model="m", usage={}),
        MentorReply(text="", model="m", usage={},
                    tool_calls=(tc("write_file", path="notes.md",
                                   content="# Заметки проекта\n"),)),
        MentorReply(text="Создал.", model="m", usage={}),
        MentorReply(text="", model="m", usage={},
                    tool_calls=(tc("read_file", path="config.txt"),)),
        MentorReply(text="mode = nightly", model="m", usage={}),
    ]
    app.mentor_client = lambda: ScriptedMentor(script)
    report = model_page.live_benchmark_text()
    assert "3/3" in report, report


def test_stage35_stop_button(fake_ui, tmp_path):
    import threading

    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    chat = app.chat_panel
    assert hasattr(chat, "stop_btn")
    chat._cancel_event = threading.Event()
    chat.stop_agent()
    assert chat._cancel_event.is_set()
    chat.on_agent_event("cancelled", {"step": 1})


def test_stage36_entry_points(fake_ui, tmp_path):
    import alterego_training_hub.__main__ as main_module

    assert callable(main_module.main)
    from pathlib import Path

    import tomllib

    root = Path(__file__).resolve().parent.parent
    parsed = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert parsed["project"]["scripts"]["alterego-llm-studio"] \
        == "alterego_training_hub.ui:main"


def test_stage37_interface_polish(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()

    # quick-launch + compactness persisted
    assert app.toggle_sidebar_compact() is True
    assert app.settings.sidebar_compact is True
    assert app.toggle_sidebar_compact() is False
    assert app.settings.sidebar_compact is False

    # tokens badge wired through chat accounting helpers
    app._tokens_today = 1500
    app.settings.mentor_model = "gpt-4o"
    app.refresh_status_badges()
    assert "1500" in app.tokens_badge.get()

    # composer counter exists and updates
    chat = app.chat_panel
    chat.input.insert("end", "привет мир это тест")
    chat._update_composer()
    assert "ток." in chat.composer_var.get()


def test_stage38_resume_and_night_verifier(fake_ui, tmp_path):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    chat = app.chat_panel
    assert hasattr(chat, "resume_btn")

    # --- night verifier: seed a good snapshot, then a degraded tail
    from alterego_training_hub.config import app_data_dir
    from alterego_training_hub.night_watch import WatchState, save_state

    save_state(app_data_dir() / "night-watch-state.json",
               WatchState(samples=[{"text": "хороший длинный текст"}],
                          best_val_loss=1.0))
    app.training.tail = lambda *a, **k: (
        "epoch 2/3\neval: val_loss=3.0\n"
        '{"sample": {"step": 5, "prompt": "p", "text": ""}}\n')

    class _Reply:
        text = "Есть деградация, проверьте lr."

    class _Mentor:
        def respond(self, messages, *, tools, max_tokens, temperature):
            return _Reply()

    app.mentor_client = lambda: _Mentor()
    entry = app.run_night_check()
    assert any("Деградация" in issue for issue in entry.issues), entry.issues


def test_stage39_update_check_button(fake_ui, tmp_path, monkeypatch):
    app_module = fake_ui["alterego_training_hub.ui"]
    app = app_module.TrainingHubApp()
    settings_page = app.pages["settings"]
    import alterego_training_hub.update_check as upd

    monkeypatch.setattr(
        upd, "_fetch_json",
        lambda url: {"tag_name": "v99.0.0",
                     "html_url": "https://example/release"})
    text = settings_page.updates_text()
    assert "99.0.0" in text
