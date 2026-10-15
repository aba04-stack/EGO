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

    app = TrainingHubApp()
    assert isinstance(app, tk.Tk)
    app.update_idletasks()
    app.update()

    expected = {"training", "editor", "search", "settings"}
    missing = expected - set(app.pages)
    assert not missing, f"pages missing: {missing}"
    assert hasattr(app, "chat_panel"), "docked chat panel missing"
    for page in sorted(expected):
        app.show_page(page)
        app.update_idletasks()
        app.update()

    root = app.workspace_root()
    print(f"tk-smoke OK: {len(app.pages)} pages, workspace={root}")
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
