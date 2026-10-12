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
        return []

    def delete(self, *items):
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
    tk_mod.Text = _Widget
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

    assert set(app.pages) == {"chat", "workspace", "models", "training", "gpu", "settings"}
    for key in ["chat", "workspace", "models", "training", "gpu", "settings"]:
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
