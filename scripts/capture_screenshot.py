#!/usr/bin/env python3
"""Capture the real EGO Tk window under a virtual X display for the README."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SAMPLE_PY = '''"""Minimal training loop sketch used for the README screenshot."""
from pathlib import Path


def main() -> None:
    data = Path("data.jsonl")
    print(f"EGO workspace ready · {data}")
    for step in range(3):
        loss = 2.4 / (step + 1)
        print(f"step {step:03d}  val_loss={loss:.4f}")


if __name__ == "__main__":
    main()
'''


def _seed_workspace() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ego-screenshot-ws-"))
    (root / "train.py").write_text(SAMPLE_PY, encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    return root


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: capture_screenshot.py OUTPUT.png", file=sys.stderr)
        return 2

    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="ego-screenshot-config-")
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"

    from PIL import ImageGrab

    from alterego_training_hub.theme import set_palette
    from alterego_training_hub.ui import TrainingHubApp

    workspace = _seed_workspace()
    set_palette("dark")
    app = TrainingHubApp()
    app.settings.ui_theme = "dark"
    app.settings.workspace_path = str(workspace)
    app._refresh_workspace_badge()
    app.geometry("1480x860+0+0")
    failures: list[BaseException] = []
    captured = False

    def prepare() -> None:
        try:
            editor = app.pages.get("editor")
            if editor is not None:
                editor.refresh_tree()
                editor.open_file(workspace / "train.py")
            app.show_page("editor")
            app.show_bottom("terminal")
            app.update_idletasks()
            app.update()
        except BaseException as exc:
            failures.append(exc)

    def capture() -> None:
        nonlocal captured
        try:
            prepare()
            app.update_idletasks()
            app.update()
            x, y = app.winfo_rootx(), app.winfo_rooty()
            width, height = app.winfo_width(), app.winfo_height()
            if width < 1200 or height < 700:
                raise RuntimeError(f"Unexpected EGO window size: {width}x{height}")
            image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            if image.width < 1200 or image.height < 700:
                raise RuntimeError(f"Screenshot too small: {image.width}x{image.height}")
            image.save(output, format="PNG")
            captured = True
            print(f"Captured actual EGO app window: {output} ({image.width}x{image.height})")
        except BaseException as exc:
            failures.append(exc)
        finally:
            app.after(200, app.destroy)

    def timeout() -> None:
        if not captured and not failures:
            failures.append(TimeoutError("EGO did not finish rendering within 20 seconds"))
            app.destroy()

    app.after(1600, capture)
    app.after(20000, timeout)
    try:
        app.mainloop()
    except BaseException as exc:
        failures.append(exc)
    if failures:
        for exc in failures:
            print(f"Screenshot capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not output.is_file() or output.stat().st_size < 10_000:
        print(f"Screenshot output is missing or unexpectedly small: {output}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
