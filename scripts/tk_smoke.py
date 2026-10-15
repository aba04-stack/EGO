"""Real Tk layout smoke test (run under xvfb).

Exercises the actual desktop shell at a compact and a normal size, including
sidebar labels, the editor, the collapsible project form, and mentor actions.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ego-tk-smoke-")
    os.environ["XDG_CONFIG_HOME"] = tmp
    os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

    import tkinter as tk
    from tkinter import font as tkfont

    from alterego_training_hub.ui import TrainingHubApp

    try:
        app = TrainingHubApp()
    except BaseException:
        # The GUI crash hook can hide tracebacks behind a modal dialog in CI.
        sys.__excepthook__(*sys.exc_info())
        return 1
    sys.excepthook = sys.__excepthook__
    assert isinstance(app, tk.Tk)
    app.update_idletasks()
    app.update()

    expected = {"chat", "training", "editor", "search", "settings"}
    missing = expected - set(app.pages)
    assert not missing, f"pages missing: {missing}"
    assert hasattr(app, "chat_panel"), "docked mentor panel missing"

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

    editor = app.pages["editor"]
    panel = app.chat_panel

    def verify_layout(geometry: str) -> None:
        app.geometry(geometry)
        app.show_page("editor")
        app.update_idletasks()
        app.update()

        assert editor.tree.winfo_ismapped(), "Editor file tree is hidden"
        assert editor.editor.winfo_ismapped(), "Main code editor is hidden"
        for widget, name in (
            (editor.refresh_tree_button, "refresh-files button"),
            (editor.open_selected_button, "open-file button"),
            (editor.new_name_entry, "new-file name field"),
            (editor.create_file_button, "create-file button"),
            (editor.rename_file_button, "rename-file button"),
            (editor.delete_file_button, "delete-file button"),
        ):
            assert widget.winfo_ismapped(), f"{name} is hidden at {geometry}"
            assert_inside(widget, editor.tree.master, name)
            if widget is not editor.new_name_entry:
                assert widget.winfo_reqwidth() <= widget.winfo_width() + 1, (
                    f"{name} text/control is clipped at {geometry}: "
                    f"requested={widget.winfo_reqwidth()}px, "
                    f"actual={widget.winfo_width()}px"
                )
        assert editor.editor.winfo_width() > 80, (
            f"Main code editor has no usable width at {geometry}: "
            f"{editor.editor.winfo_width()}px"
        )
        assert editor.editor.winfo_height() > 60, (
            f"Main code editor has no usable height at {geometry}: "
            f"{editor.editor.winfo_height()}px"
        )

        for key, button in app._nav_buttons.items():
            font = tkfont.Font(root=app, font=button.cget("font"))
            try:
                padx = int(button.cget("padx"))
            except (TypeError, ValueError):
                padx = 8
            available = max(0, button.winfo_width() - 2 * padx)
            actual = font.measure(button.cget("text"))
            assert actual <= available + 1, (
                f"Sidebar label {key!r} clips at {geometry}: "
                f"text={actual}px, available={available}px, "
                f"label={button.cget('text')!r}"
            )

        for widget, name in (
            (panel.sessions_combo, "mentor session selector"),
            (panel.new_session_btn, "new dialogue button"),
            (panel.delete_session_btn, "delete dialogue button"),
            *[
                (button, f"mentor action {index}")
                for index, button in enumerate(panel.session_action_buttons)
            ],
        ):
            assert widget.winfo_ismapped(), f"{name} is hidden at {geometry}"
            assert_inside(widget, panel, name)

        # Expand the project form to validate its narrow-width layout too.
        editor.scaffold_section.set_open(True)
        app.update_idletasks()
        app.update()
        for widget, name in (
            (editor.project_label, "project label"),
            (editor.project_entry, "project name field"),
            (editor.template_combo, "project template selector"),
            (editor.project_create_button, "create-project button"),
        ):
            assert widget.winfo_ismapped(), f"{name} is hidden at {geometry}"
            assert_inside(widget, editor._project_form_row, name)
        editor.scaffold_section.set_open(False)
        app.update_idletasks()
        app.update()
        assert editor.editor.winfo_ismapped(), (
            f"Main code editor disappeared after collapsing form at {geometry}"
        )

    for page in sorted(expected):
        app.show_page(page)
        app.update_idletasks()
        app.update()

    verify_layout("1180x720+0+0")
    verify_layout("1480x860+0+0")

    root = app.workspace_root()
    print(
        f"tk-smoke OK: {len(app.pages)} pages; compact and desktop layouts "
        f"verified; workspace={root}"
    )
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
