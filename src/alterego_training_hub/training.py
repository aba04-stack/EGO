"""Run a training command inside the workspace and capture its log.

The process runs without a shell in the chosen workspace folder, streams its
combined output to a log file, and can be stopped safely. The mentor can then
read the log and propose fixes through the chat panel.
"""
from __future__ import annotations

import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import app_data_dir


class TrainingError(RuntimeError):
    """Training configuration or state error safe to display."""


@dataclass(frozen=True)
class TrainingStatus:
    running: bool
    returncode: int | None
    log_path: str
    started_at: float | None
    command: str


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
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self._log_path = self.log_dir / f"training-{stamp}.log"
            handle = self._log_path.open("w", encoding="utf-8")
            handle.write(f"# command: {command}\n# workspace: {root}\n# started: {stamp}\n\n")
            handle.flush()
            try:
                self._process = subprocess.Popen(
                    argv,
                    cwd=str(root),
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
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
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()

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
        raw = path.read_bytes()
        if len(raw) > max_bytes:
            raw = raw[-max_bytes:]
        return raw.decode("utf-8", errors="replace")

    def list_logs(self) -> list[Path]:
        return sorted(self.log_dir.glob("training-*.log"), reverse=True)
