"""Этап 48: общий apply_guard, демон бюджета в приложении."""
import time

from alterego_training_hub.budget_guard import BudgetLedger, apply_guard


def _pods(*specs):
    return [{"id": pid, "status": status, "costPerHr": cost}
            for pid, status, cost in specs]


def test_apply_guard_syncs_and_stops(tmp_path):
    ledger = BudgetLedger.load(tmp_path / "b.json")
    now = time.time()
    ledger.observe("old", 1.0, now=now - 7200, managed=True)  # already 2h accrued
    # "new" не создан приложением: учитывается, но не автостопится
    ledger.observe("new", 0.5, now=now - 7200, managed=True)
    stopped = []
    verdict = apply_guard(
        ledger,
        _pods(("old", "RUNNING", 1.0), ("new", "RUNNING", 0.5)),
        cap_usd=1.0, stopper=stopped.append, now=now)
    assert verdict.over and set(stopped) == {"old", "new"}
    reloaded = BudgetLedger.load(tmp_path / "b.json")
    assert reloaded.pods["old"].stopped_at == now


def test_apply_guard_marks_gone_pods_stopped(tmp_path):
    ledger = BudgetLedger.load(tmp_path / "b.json")
    now = time.time()
    apply_guard(ledger, _pods(("p1", "RUNNING", 1.0)), 0.0, now=now)
    apply_guard(ledger, [], 0.0, now=now + 60)   # пропуск 1: ещё жив
    assert ledger.pods["p1"].stopped_at == 0.0
    apply_guard(ledger, [], 0.0, now=now + 120)  # пропуск 2: остановлен
    assert ledger.pods["p1"].stopped_at == now + 120


def test_apply_guard_no_cap_observes_only(tmp_path):
    ledger = BudgetLedger.load(tmp_path / "b.json")
    verdict = apply_guard(ledger, _pods(("p1", "RUNNING", 3.0)), 0.0,
                          now=time.time())
    assert not verdict.over and verdict.stopped == []
