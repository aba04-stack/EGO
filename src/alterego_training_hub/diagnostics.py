"""Environment diagnostics ("Доктор"): verify the setup and report problems.

Every check returns a plain dict so the UI, tests, and the mentor-agent can all
consume the same report. Checks never raise and never touch credentials.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .config import AppSettings, SecretStore, app_data_dir

CHECK_FIELDS = ("name", "ok", "detail", "severity")  # severity: info|warn|error


def _check(name: str, ok: bool, detail: str, severity: str = "info") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "severity": severity}


def _probe_writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(path), delete=True):
            pass
        return True, f"папка доступна для записи: {path}"
    except OSError as exc:
        return False, f"нет доступа для записи: {path} ({exc})"


def run_diagnostics(settings: AppSettings | None = None,
                    secrets: SecretStore | None = None) -> list[dict[str, Any]]:
    settings = settings or AppSettings.load()
    secrets = secrets or SecretStore()
    results: list[dict[str, Any]] = []

    # Python
    py_ok = sys.version_info >= (3, 10)
    results.append(_check(
        "Python", py_ok,
        f"{sys.version.split()[0]} (нужно >= 3.10)",
        "info" if py_ok else "error"))

    # Tkinter
    try:
        import tkinter  # noqa: F401
        results.append(_check("Tkinter", True, "доступен"))
    except ImportError:
        results.append(_check("Tkinter", False,
                              "не установлен (python3-tk / Tcl-Tk)", "error"))

    # keyring backend
    try:
        secrets.get("diagnostic.probe")
        keyring_ok, keyring_detail = True, "хранилище отвечает"
    except RuntimeError as exc:
        keyring_ok, keyring_detail = False, f"хранилище недоступно: {exc}"
    except Exception as exc:  # noqa: BLE001
        keyring_ok, keyring_detail = False, f"ошибка хранилища: {exc}"
    results.append(_check("Системное хранилище ключей", keyring_ok,
                          keyring_detail, "info" if keyring_ok else "warn"))

    # paramiko
    try:
        import paramiko
        results.append(_check("SSH (paramiko)", True,
                              f"версия {getattr(paramiko, '__version__', '?')}"))
    except ImportError:
        results.append(_check("SSH (paramiko)", False,
                              "не установлен — серверы недоступны (pip install paramiko)",
                              "warn"))

    # git
    git_path = shutil.which("git")
    if git_path:
        results.append(_check("Git", True, git_path))
    else:
        results.append(_check("Git", False,
                              "не найден в PATH — операции с репозиторием недоступны",
                              "warn"))

    # Workspace
    ws = (settings.workspace_path or "").strip()
    if not ws:
        results.append(_check("Рабочая папка", False, "не выбрана", "warn"))
    else:
        ws_path = Path(ws).expanduser()
        if not ws_path.is_dir():
            results.append(_check("Рабочая папка", False,
                                  f"не найдена: {ws_path}", "error"))
        else:
            ok, detail = _probe_writable(ws_path)
            results.append(_check("Рабочая папка", ok, detail,
                                  "info" if ok else "error"))

    # App data
    ok, detail = _probe_writable(app_data_dir())
    results.append(_check("Папка данных приложения", ok, detail,
                          "info" if ok else "error"))

    # Disk space
    try:
        usage = shutil.disk_usage(app_data_dir())
        free_gb = usage.free / (1024 ** 3)
        results.append(_check(
            "Свободное место", free_gb >= 1.0,
            f"{free_gb:.1f} ГБ",
            "info" if free_gb >= 1.0 else "warn"))
    except OSError as exc:
        results.append(_check("Свободное место", False, str(exc), "warn"))

    # Mentor
    mentor_ok = bool(settings.mentor_base_url and settings.mentor_model)
    try:
        mentor_ok = mentor_ok and bool(secrets.get("mentor_api_key"))
        mentor_detail = "провайдер, модель и ключ настроены" if mentor_ok else \
            "провайдер/модель/ключ заданы не полностью"
    except Exception:  # noqa: BLE001
        mentor_ok = False
        mentor_detail = "ключ наставника не сохранён или хранилище недоступно"
    results.append(_check("ИИ-наставник", mentor_ok, mentor_detail,
                          "info" if mentor_ok else "warn"))

    # Training command
    cmd = (settings.training_command or "").strip()
    results.append(_check("Команда обучения", bool(cmd),
                          cmd or "не задана", "info" if cmd else "warn"))

    # Servers registry
    try:
        from .servers import ServerStore
        servers = ServerStore().list()
        results.append(_check("Серверы", True,
                              f"подключено: {len(servers)}"))
    except Exception as exc:  # noqa: BLE001
        results.append(_check("Серверы", False, str(exc), "warn"))

    return results


def diagnostics_text(results: list[dict[str, Any]]) -> str:
    """Plain-text report for copying into an issue."""
    marks = {True: "ok", False: "!!"}
    lines = ["Диагностика AlterEgo Training Hub",
             f"Платформа: {os.name} / {sys.platform}",
             ""]
    for item in results:
        lines.append(f"[{marks.get(bool(item.get('ok')), '??')}] "
                     f"{item.get('name', '?')}: {item.get('detail', '')}")
    return "\n".join(lines)


def diagnostics_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [item for item in results
              if not item.get("ok") and item.get("severity") == "error"]
    warnings = [item for item in results
                if not item.get("ok") and item.get("severity") == "warn"]
    return {"ok": not errors, "errors": len(errors), "warnings": len(warnings),
            "total": len(results)}
