#!/usr/bin/env python3
"""Run the AlterEgo Training Hub desktop application from a source checkout."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    try:
        from alterego_training_hub.logging_setup import install_excepthook, setup_logging

        setup_logging()
        install_excepthook()
        from alterego_training_hub.ui import main as run_ui
    except (ImportError, ModuleNotFoundError) as exc:
        missing = getattr(exc, "name", "") or ""
        if "tkinter" in missing or "tkinter" in str(exc):
            print(
                "Tkinter is not available in this Python installation.\n"
                "  - Windows/macOS: reinstall Python with the Tcl/Tk option enabled.\n"
                "  - Debian/Ubuntu: sudo apt install python3-tk\n"
                "  - Fedora: sudo dnf install python3-tkinter",
                file=sys.stderr,
            )
            return 1
        raise
    run_ui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
