"""Application logging: rotating file log and an uncaught-exception hook.

Everything the app does lands in ``<app data>/logs/hub.log`` (rotated, no
secrets by convention). The exception hook keeps a crash from vanishing into a
closed window: it logs the traceback and shows a dialog when the GUI is alive.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from .config import app_data_dir

LOGGER_NAME = "alterego_training_hub"
_MAX_LOG_BYTES = 512 * 1024
_LOG_BACKUPS = 3

_configured = False


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    return log_dir() / "hub.log"


def setup_logging() -> Path:
    """Configure the rotating file handler once; returns the log file path."""
    global _configured
    path = log_file()
    logger = logging.getLogger(LOGGER_NAME)
    if not _configured:
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=_MAX_LOG_BYTES, backupCount=_LOG_BACKUPS,
            encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _configured = True
    return path


def get_logger(name: str = "") -> logging.Logger:
    setup_logging()
    return logging.getLogger(LOGGER_NAME + (f".{name}" if name else ""))


def tail_log(max_bytes: int = 20_000) -> str:
    """Last bytes of the log file, for diagnostics."""
    path = log_file()
    if not path.exists():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-max(200, min(int(max_bytes), 200_000)):].decode(
        "utf-8", errors="replace")


def install_excepthook() -> None:
    """Log uncaught exceptions; show a dialog if a Tk app is running."""
    def hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        text = "".join(traceback.format_exception(
            exc_type, exc_value, exc_traceback))
        try:
            get_logger("crash").error("Необработанное исключение:\n%s", text)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = getattr(tk, "_default_root", None)
            if root is not None and root.winfo_exists():
                root.after(0, lambda: messagebox.showerror(
                    "AlterEgo Training Hub",
                    "Произошла непредвиденная ошибка. Подробности записаны в лог:\n"
                    + str(log_file())))
                return
        except Exception:
            pass
        sys.stderr.write(text)

    sys.excepthook = hook


def log_worker_error(where: str, exc: BaseException) -> None:
    """Log a background-worker failure with its traceback."""
    get_logger(where).error("%s: %s\n%s", type(exc).__name__, exc,
                            "".join(traceback.format_exception(exc)))
