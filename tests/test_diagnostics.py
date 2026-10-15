"""Tests for environment diagnostics and the application log."""
from __future__ import annotations

import logging

from alterego_training_hub.config import AppSettings
from alterego_training_hub.diagnostics import (
    diagnostics_summary,
    diagnostics_text,
    run_diagnostics,
)
from alterego_training_hub.logging_setup import (
    get_logger,
    install_excepthook,
    log_worker_error,
    setup_logging,
    tail_log,
)


class FakeSecrets:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        if key not in self.data:
            raise RuntimeError("нет ключа")
        return self.data[key]


def test_diagnostics_reports_structured_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings = AppSettings(workspace_path=str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    results = run_diagnostics(settings, FakeSecrets())

    names = [item["name"] for item in results]
    assert {"Python", "Tkinter", "Системное хранилище ключей", "Git",
            "Рабочая папка", "Папка данных приложения", "Свободное место",
            "ИИ-наставник", "Команда обучения"} <= set(names)
    for item in results:
        assert set(item) == {"name", "ok", "detail", "severity"}
        assert item["severity"] in {"info", "warn", "error"}

    by_name = {item["name"]: item for item in results}
    assert by_name["Python"]["ok"] is True
    assert by_name["Рабочая папка"]["ok"] is True
    assert by_name["ИИ-наставник"]["ok"] is False  # not configured
    assert by_name["Системное хранилище ключей"]["ok"] is False  # fake raises

    text = diagnostics_text(results)
    assert "Диагностика" in text and "[ok]" in text
    summary = diagnostics_summary(results)
    assert summary["total"] == len(results)
    assert summary["warnings"] >= 1


def test_diagnostics_flags_missing_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    settings = AppSettings(workspace_path=str(tmp_path / "nope"))
    results = run_diagnostics(settings, FakeSecrets())
    ws = next(item for item in results if item["name"] == "Рабочая папка")
    assert ws["ok"] is False and ws["severity"] == "error"


def test_logging_setup_writes_rotating_log(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = setup_logging()
    assert path.exists() or path.parent.is_dir()

    logger = get_logger("test")
    logger.info("привет из теста")
    for handler in logging.getLogger("alterego_training_hub").handlers:
        handler.flush()

    tail = tail_log()
    assert "привет из теста" in tail

    # worker errors are logged with a traceback
    try:
        raise ValueError("случайная ошибка")
    except ValueError as exc:
        log_worker_error("test", exc)
    for handler in logging.getLogger("alterego_training_hub").handlers:
        handler.flush()
    assert "ValueError" in tail_log()

    install_excepthook()  # installs without raising
