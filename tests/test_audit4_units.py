"""Четвёртый аудит: поведенческие тесты (semver, настройки, очереди, бюджет)."""
from __future__ import annotations

import itertools
import json

from alterego_training_hub.budget_guard import BudgetLedger, apply_guard
from alterego_training_hub.cloud_queue import CloudJob, CloudJobQueue
from alterego_training_hub.config import AppSettings
from alterego_training_hub.update_check import is_newer


# 12: полный порядок SemVer для prerelease
def test_semver_prerelease_order():
    chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta",
             "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
             "1.0.0-rc.1", "1.0.0"]
    for lower, higher in itertools.pairwise(chain):
        assert is_newer(higher, lower), (lower, higher)
        assert not is_newer(lower, higher), (lower, higher)
    assert is_newer("1.0.0-beta1", "1.0.0-alpha2")


# 9: поля с default_factory валидируются
def test_settings_factory_fields_validated(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "hotkeys": "не словарь", "plugin_market_urls": {"a": 1},
        "mentor_model": "ok"}), encoding="utf-8")
    loaded = AppSettings.load(path)
    assert loaded.hotkeys == {} and loaded.plugin_market_urls == []
    assert "hotkeys" in loaded.load_error
    assert "plugin_market_urls" in loaded.load_error
    assert loaded.mentor_model == "ok"


# 10: повреждённая очередь: копия + load_error, валидные записи живы
def test_cloud_queue_corrupt_file(tmp_path):
    queue = CloudJobQueue(tmp_path)
    queue.path.write_text("{битый", encoding="utf-8")
    assert queue._load() == []
    assert queue.load_error and "повреждён" in queue.load_error
    assert list(tmp_path.glob("cloud_jobs.json.corrupt-*"))
    queue2 = CloudJobQueue(tmp_path / "q2")
    queue2.path.parent.mkdir(parents=True, exist_ok=True)
    queue2.path.write_text(json.dumps([
        {"name": "ok", "command": "python t.py"},
        {"name": 123, "command": "x", "bogus": object.__class__.__name__},
        "не объект"]), encoding="utf-8")
    # битые записи не роняют загрузку валидных, но фиксируются
    try:
        rows = queue2._load()
    except Exception:
        rows = []
    assert len(rows) >= 1


# 6: сбой сохранения бюджета попадает в verdict.warning
def test_budget_save_failure_warns(tmp_path, monkeypatch):
    ledger = BudgetLedger.load(tmp_path / "budget.json")
    ledger.observe("p1", 1.0, now=0.0, managed=True)
    def boom():
        raise OSError("диск переполнен")
    monkeypatch.setattr(ledger, "save", boom)
    verdict = apply_guard(ledger, [], cap_usd=100.0, now=3600.0)
    assert "автостоп под угрозой" in verdict.warning
    assert "автостоп под угрозой" in verdict.render()


# 6б: сбой записи бюджета при submit виден в логе задания
def test_submit_budget_failure_visible(tmp_path, monkeypatch):
    from alterego_training_hub import budget_guard

    class FakeClient:
        def create_pod(self, plan, confirmed=False):
            return {"id": "pod-7", "confirmed_gpu_hourly_usd": 0.5}

    def broken_load(cls, *a, **k):
        raise OSError("нет доступа")
    monkeypatch.setattr(budget_guard.BudgetLedger, "load",
                        classmethod(broken_load))
    queue = CloudJobQueue(tmp_path)
    job = queue.add(CloudJob(name="t", command="python t.py"))
    updated = queue.submit(job.id, FakeClient())
    assert updated.status == "submitted"
    assert "автостоп" in updated.log
