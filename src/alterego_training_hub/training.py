"""Run a training command inside the workspace and capture its log.

The process runs without a shell in the chosen workspace folder, streams its
combined output to a log file, and can be stopped safely. The mentor can then
read the log and propose fixes through the chat panel.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import app_data_dir


class TrainingError(RuntimeError):
    """Training configuration or state error safe to display."""


# ------------------------------------------------------------- hot control
# ``control.json`` in the workspace root lets the user and the mentor agent
# adjust a running training between epochs. The generated train.py reads it
# every epoch and applies the recognised keys; ``stop`` is consumed once.
CONTROL_FILENAME = "control.json"
CONTROL_KEYS = ("lr", "max_epochs", "early_stop_patience", "grad_clip",
                "stop", "note")


def control_path(root: str | Path) -> Path:
    return Path(root).expanduser() / CONTROL_FILENAME


def read_control(root: str | Path) -> dict:
    path = control_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_control(root: str | Path, params: dict[str, object]) -> dict:
    """Merge recognised control parameters into ``control.json`` atomically."""
    if not isinstance(params, dict):
        raise TrainingError("Параметры управления должны быть объектом.")
    current = read_control(root)
    updates: dict[str, object] = {}
    for key, value in params.items():
        if key not in CONTROL_KEYS:
            raise TrainingError(f"Неизвестный параметр управления: {key}")
        if key == "note":
            updates[key] = str(value)[:200]
        elif key == "stop":
            updates[key] = bool(value)
        elif key in {"max_epochs", "early_stop_patience"}:
            updates[key] = max(0, int(value))
        else:
            updates[key] = float(value)
    current.update(updates)
    path = control_path(root)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return current


@dataclass(frozen=True)
class TrainingStatus:
    running: bool
    returncode: int | None
    log_path: str
    started_at: float | None
    command: str


def _signal_process_tree(process, *, kill: bool) -> None:
    """SIGTERM/SIGKILL the process group on POSIX; plain call elsewhere."""
    import signal as _signal

    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid),
                      _signal.SIGKILL if kill else _signal.SIGTERM)
        elif kill:
            process.kill()
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill() if kill else process.terminate()
        except Exception:
            pass


class TrainingRun:
    """Manages one training process at a time."""

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = Path(log_dir) if log_dir else (app_data_dir() / "training-logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._log_path: Path | None = None
        self._started_at: float | None = None
        self._command: str = ""
        self._returncode: int | None = None

    def start(self, command: str, workspace: str | Path, *,
              timeout_seconds: float | None = None) -> str:
        if not isinstance(command, str) or not command.strip():
            raise TrainingError("Укажите команду обучения, например python scripts/train.py.")
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise TrainingError(f"Рабочая папка не найдена: {root}")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise TrainingError(f"Не удалось разобрать команду: {exc}") from None
        if not argv:
            raise TrainingError("Команда обучения не должна быть пустой.")

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise TrainingError("Обучение уже запущено. Сначала остановите его.")
            stamp = (time.strftime("%Y%m%d-%H%M%S")
                     + f"-{int((time.time() % 1) * 1e6):06d}-{os.getpid()}")
            self._log_path = self.log_dir / f"training-{stamp}.log"
            handle = self._log_path.open("w", encoding="utf-8")
            handle.write(f"# command: {command}\n# workspace: {root}\n# started: {stamp}\n\n")
            handle.flush()
            try:
                popen_kwargs: dict = {}
                if os.name == "posix":
                    popen_kwargs["start_new_session"] = True  # своя группа: stop добивает детей
                self._process = subprocess.Popen(
                    argv,
                    cwd=str(root),
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **popen_kwargs,
                )
            except FileNotFoundError:
                handle.close()
                self._process = None
                raise TrainingError(f"Команда не найдена: {argv[0]}") from None
            self._started_at = time.time()
            self._command = command
            self._returncode = None
            process = self._process

        def waiter():
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            finally:
                handle.close()
                with self._lock:
                    self._returncode = process.returncode

        threading.Thread(target=waiter, daemon=True).start()
        return str(self._log_path)

    def stop(self) -> None:
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            raise TrainingError("Сейчас ничего не запущено.")
        _signal_process_tree(process, kill=False)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _signal_process_tree(process, kill=True)

    def status(self) -> TrainingStatus:
        with self._lock:
            process = self._process
            running = process is not None and process.poll() is None
            return TrainingStatus(
                running=running,
                returncode=None if running else self._returncode,
                log_path=str(self._log_path or ""),
                started_at=self._started_at,
                command=self._command,
            )

    def tail(self, max_bytes: int = 20_000) -> str:
        with self._lock:
            path = self._log_path
        if path is None or not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read(max_bytes)
        return raw.decode("utf-8", errors="replace")

    def list_logs(self) -> list[Path]:
        return sorted(self.log_dir.glob("training-*.log"), reverse=True)
