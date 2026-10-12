"""Headless UI smoke test: build every page with a fake tkinter and poke it.

This catches wiring errors between pages and the app shell without needing a
display server or a real Tk installation.
"""
from __future__ import annotations

import sys
import types

import pytest


class _Widget:
    """Permissive widget stand-in: any method call is a harmless no-op."""

    def __init__(self, *args, **kwargs):
        pass

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

    def insert(self, parent, index, **kwargs):
        item_id = f"item-{len(self._items)}"
        self._items.append((item_id, kwargs))
        return item_id

    def get_children(self):
        return [item_id for item_id, _ in self._items]

    def delete(self, *items):
        if items:
            self._items = []

    def selection(self):
        return ()

    def heading(self, *args, **kwargs):
        pass

    def column(self, *args, **kwargs):
        pass


class _Listbox(_Widget):
    def curselection(self):
        return ()


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


class _Style(_Widget):
    def theme_use(self, name):
        pass


TclError = type("TclError", (Exception,), {})


def _fake_tkinter():
    tk_mod = types.ModuleType("tkinter")
    tk_mod.Tk = _Tk
    tk_mod.Frame = _Widget
    tk_mod.Label = _Widget
    tk_mod.Entry = _Widget
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
    ttk_mod.Entry = _Widget
    ttk_mod.Combobox = _Widget
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
        "alterego_training_hub.ui_models",
        "alterego_training_hub.ui_training",
        "alterego_training_hub.ui_gpu",
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

    assert set(app.pages) == {"chat", "editor", "workspace", "models", "datasets",
                              "model", "playground", "training", "gpu", "settings"}
    for key in ["chat", "editor", "workspace", "models", "datasets", "model",
                "playground", "training", "gpu", "settings"]:
        app.show_page(key)
    assert app._current_page == "settings"

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

    tools, schemas = app.agent_extra_tools()
    assert set(tools) == {"get_training_status", "read_training_log", "get_run_history"}
    assert tools["get_training_status"]({})["ok"] is True
    assert tools["read_training_log"]({"max_bytes": 1000})["ok"] is True
    assert tools["get_run_history"]({"limit": 3})["ok"] is True
    assert len(schemas) == 3

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
