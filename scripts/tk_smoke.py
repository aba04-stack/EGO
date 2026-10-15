"""Real-Tk smoke test (stage 40): needs a display — run under xvfb.

Creates the actual application window with a temporary config home,
opens several pages, pumps the event loop, and destroys the window.
Exits non-zero on any failure so CI can gate on it.

    xvfb-run -a python scripts/tk_smoke.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="alterego-tk-smoke-")
    os.environ["XDG_CONFIG_HOME"] = tmp
    os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

    import tkinter as tk

    from alterego_training_hub.ui import TrainingHubApp

    try:
        app = TrainingHubApp()
    except BaseException:
        # The GUI's crash hook intentionally opens a dialog and can hide
        # tracebacks in headless CI; print the startup error for diagnostics.
        sys.__excepthook__(*sys.exc_info())
        return 1
    # Expose test failures directly rather than through a modal GUI dialog.
    sys.excepthook = sys.__excepthook__
    assert isinstance(app, tk.Tk)
    app.update_idletasks()
    app.update()

    expected = {"chat", "training", "editor", "search", "settings"}
    missing = expected - set(app.pages)
    assert not missing, f"pages missing: {missing}"
    assert hasattr(app, "chat_panel"), "docked chat panel missing"
    for page in sorted(expected):
        app.show_page(page)
        app.update_idletasks()
        app.update()

    from tkinter import font as tkfont

    editor = app.pages["editor"]

    def assert_inside(widget, parent, description: str) -> None:
        parent_left = parent.winfo_rootx()
        parent_right = parent_left + parent.winfo_width()
        widget_left = widget.winfo_rootx()
        widget_right = widget_left + widget.winfo_width()
        assert widget_left >= parent_left - 1, (
            f"{description} starts outside its container: "
            f"{widget_left} < {parent_left}"
        )
        assert widget_right <= parent_right + 1, (
            f"{description} clips outside its container: "
            f"{widget_right} > {parent_right}"
        )

    def verify_layout(geometry: str) -> None:
        app.geometry(geometry)
        app.show_page("editor")
        app.update_idletasks()
        app.update()

        assert editor.tree.winfo_ismapped(), (
            "Editor file tree is hidden; card containers must be managed "
            "by their actual parent."
        )
        assert editor.editor.winfo_ismapped(), "Main code editor is hidden"

        for key, button in app._nav_buttons.items():
            font = tkfont.Font(root=app, font=button.cget("font"))
            try:
                padx = int(button.cget("padx"))
            except (TypeError, ValueError):
                padx = 8
            available = max(0, button.winfo_width() - 2 * padx)
            actual = font.measure(button.cget("text"))
            assert actual <= available + 1, (
                f"Sidebar label {key!r} is clipped at {geometry}: "
                f"text={actual}px, available={available}px, "
                f"label={button.cget('text')!r}"
            )

        project_row = editor._project_form_row
        for widget, name in (
            (editor.project_label, "project label"),
            (editor.project_entry, "project name"),
            (editor.template_combo, "template selector"),
            (editor.project_create_button, "create-project button"),
        ):
            assert widget.winfo_ismapped(), f"{name} is hidden at {geometry}"
            assert_inside(widget, project_row, name)

        panel = app.chat_panel
        for widget, name in (
            (panel.sessions_combo, "chat session selector"),
            (panel.new_session_btn, "new chat button"),
            (panel.delete_session_btn, "delete chat button"),
            *[
                (button, f"chat action {index}")
                for index, button in enumerate(panel.session_action_buttons)
            ],
        ):
            assert widget.winfo_ismapped(), f"{name} is hidden at {geometry}"
            assert_inside(widget, panel, name)

    # Exercise the layout at the supported minimum size and at a desktop size.
    # These assertions catch clipped labels, controls, and invisible cards.
    verify_layout("1180x720+0+0")
    verify_layout("1480x860+0+0")

    root = app.workspace_root()
    print(f"tk-smoke OK: {len(app.pages)} pages, responsive layout verified, workspace={root}")
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
