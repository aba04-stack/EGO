"""Build a standalone desktop bundle with PyInstaller.

Run this on the target OS — on Windows it produces ``dist/EGO.exe``
(windowed, one file); on Linux/macOS a same-named executable. Requires a
desktop Python with Tk available (the app itself is a Tk program).

    python scripts/build_desktop.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "EGO"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found — installing…")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "pyinstaller"])
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", APP_NAME,
        "--paths", str(ROOT / "src"),
        # keyring discovers backends via entry points; collect them explicitly.
        "--collect-submodules", "keyring.backends",
        "--add-data",
        f"{ROOT / 'src' / 'alterego_training_hub' / 'assets' / 'fonts'}"
        f"{';' if sys.platform.startswith('win') else ':'}"
        "alterego_training_hub/assets/fonts",
        str(ROOT / "run_app.py"),
    ]
    print("Running:", " ".join(command))
    subprocess.check_call(command, cwd=ROOT)
    dist = ROOT / "dist"
    bundles = sorted(dist.glob(f"{APP_NAME}*"))
    if not bundles:
        print("Build finished but no bundle found in", dist)
        return 1
    for bundle in bundles:
        print("Built:", bundle)
    print("Copy the bundle to the target machine and run it (no Python needed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
