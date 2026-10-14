"""Tests for the night watch: windows, scheduling, checks, morning sum."""
from __future__ import annotations

import time

import pytest

from alterego_training_hub.night_watch import (NightWatchError, NightWatchLog,
                                               WatchConfig, WatchEntry,
                                               config_from_dict,
                                               config_to_dict, due,
                                               morning_report, run_check)


class FakeReply:
    def __init__(self, text):
        self.text = text


class FakeMentor:
    def __init__(self, text="Обучение стабильно. Рисков нет. Снизить lr к утру.",
                 fail=False):
        self.text = text
        self.fail = fail
        self.calls = []

    def respond(self, messages, *, tools, max_tokens, temperature):
        self.calls.append({"messages": messages, "tools": tools,
                           "max_tokens": max_tokens,
                           "temperature": temperature})
        if self.fail:
            raise RuntimeError("ментор недоступен")
        return FakeReply(self.text)


def test_watch_window_crosses_midnight():
    config = WatchConfig(start="22:00", end="08:00")
    base = time.mktime((2026, 10, 14, 12, 0, 0, 0, 0, -1))
    assert config.in_window(base) is False            # noon
    assert config.in_window(base + 11 * 3600) is True  # 23:00
    assert config.in_window(base + 15 * 3600) is True  # 03:00 next day
    assert config.in_window(base + 20 * 3600) is True  # 08:00 edge
    day = WatchConfig(start="09:00", end="18:00")
    assert day.in_window(base) is True               # noon is inside
    assert day.in_window(base + 8 * 3600) is False   # 20:00 outside
    assert day.in_window(base - 2 * 3600) is True    # 10:00 inside


def test_watch_config_validation():
    WatchConfig().validate()
    with pytest.raises(NightWatchError):
        WatchConfig(start="25:00").validate()
    with pytest.raises(NightWatchError):
        WatchConfig(interval_minutes=1).validate()
    with pytest.raises(NightWatchError):
        config_from_dict({"start": "вечер"})
    restored = config_from_dict(config_to_dict(
        WatchConfig(enabled=True, interval_minutes=45)))
    assert restored.enabled is True and restored.interval_minutes == 45


def test_due_interval():
    now = time.time()
    assert due(now - 31 * 60, now=now, interval_minutes=30) is True
    assert due(now - 10 * 60, now=now, interval_minutes=30) is False
    assert due(0.0, now=now, interval_minutes=30) is True
    assert due(now - 100, now=now, interval_minutes="x") is False


def test_run_check_uses_mentor_contract():
    mentor = FakeMentor()
    entry = run_check(mentor, tail="epoch 1/3 loss=2.0",
                      dashboard="📊 Дашборд", issues=["спайк"])
    assert entry.ok is True
    assert entry.summary.startswith("Обучение стабильно")
    assert entry.issues == ["спайк"]
    call = mentor.calls[0]
    assert call["tools"] is None
    assert call["max_tokens"] == 400 and call["temperature"] == 0.2
    assert "Дашборд" in call["messages"][0]["content"]
    assert "epoch 1/3" in call["messages"][0]["content"]
    assert "спайк" in call["messages"][0]["content"]


def test_run_check_survives_mentor_failures():
    entry = run_check(FakeMentor(fail=True), tail="", dashboard="")
    assert entry.ok is False
    assert "ошибка опроса" in entry.summary
    assert any("ментор недоступен" in issue for issue in entry.issues)


def test_night_watch_log_round_trip(tmp_path):
    log = NightWatchLog(tmp_path / "night" / "watch.json")
    assert log.entries() == []
    log.add(WatchEntry(summary="всё хорошо"))
    log.add(WatchEntry(at=123.0, summary="спайк", issues=["lr"], ok=False))
    entries = log.entries()
    assert len(entries) == 2
    assert entries[1].issues == ["lr"] and entries[1].ok is False
    log.clear()
    assert log.entries() == []
    (tmp_path / "watch.json").write_text("{bad", encoding="utf-8")
    assert NightWatchLog(tmp_path / "watch.json").entries() == []


def test_morning_report_summary():
    text = morning_report([])
    assert "Ночных проверок не было" in text
    entries = [
        WatchEntry(summary="норма", ok=True),
        WatchEntry(summary="спайк loss", issues=["спайк на шаге 4"], ok=False),
        WatchEntry(summary="восстановилось", ok=True),
    ]
    report = morning_report(entries, title="Дежурство 14.10")
    assert "Дежурство 14.10" in report
    assert "Проверок: 3" in report and "с проблемами: 1" in report
    assert "спайк loss" in report
    assert "Последнее наблюдение" in report
    assert "спайк на шаге 4" in report
