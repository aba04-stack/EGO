"""Regression tests for the external 28-point audit (v1.8.2)."""
from __future__ import annotations

import pytest

from alterego_training_hub.budget_guard import BudgetLedger, apply_guard
from alterego_training_hub.compare import _final_loss, _metric_name, compare_runs
from alterego_training_hub.datasets import preview_rows
from alterego_training_hub.metrics import MetricPoint, MetricsSummary
from alterego_training_hub.tools import WorkspaceTools
from alterego_training_hub.train_script import ScriptConfig, generate_script


def _summary(values):
    points = [MetricPoint(step=i + 1, epoch=i + 1, values=v)
              for i, v in enumerate(values)]
    return MetricsSummary(points=points, last=dict(points[-1].values),
                          epoch_current=len(points), epochs_total=len(points))


# 1: LoRA должен строить labels, иначе модель нечему учиться
def test_lora_script_builds_labels():
    script = generate_script(ScriptConfig(path="lora", dataset_path="d.jsonl",
                                          base_model="m"))
    assert "_mask_labels" in script and '"labels": labels' in script


# 2/3/4: scratch: настоящий val, messages/битые строки, бандл чекпоинта
def test_scratch_script_has_real_val_and_bundle(tmp_path):
    script = generate_script(ScriptConfig(path="scratch", dataset_path="d.txt"))
    assert "train_data, val_data = (data[:-n_val]" in script
    assert '"state_dict": raw_model.state_dict()' in script
    assert '"stoi": stoi' in script
    compile(script, "train_llm.py", "exec")


def test_generated_script_row_text_variants(tmp_path):
    script = generate_script(
        ScriptConfig(path="scratch", dataset_path=str(tmp_path / "d.jsonl")))
    assert "_row_text" in script and "messages" in script


# 8-10: сравнение только по одной сопоставимой метрике
def test_compare_uses_val_loss_not_train():
    a = _summary([{"loss": 0.1, "val_loss": 2.0}, {"loss": 0.05, "val_loss": 1.9}])
    b = _summary([{"loss": 3.0, "val_loss": 1.0}, {"loss": 2.0, "val_loss": 0.9}])
    assert _metric_name(a) == "val_loss" and _final_loss(a) == 1.9
    report = compare_runs(a, b, label_a="A", label_b="B")
    assert report.winner == "b"  # по val_loss хуже A, по loss — наоборот


def test_compare_incomparable_metrics():
    a = _summary([{"loss": 1.0}, {"loss": 0.5}])
    b = _summary([{"val_loss": 1.0}, {"val_loss": 0.4}])
    report = compare_runs(a, b, label_a="A", label_b="B")
    assert report.winner == "" and "Несопоставимо" in report.verdict


# 12: preview не обрезан на 200k символов
def test_preview_csv_beyond_200k(tmp_path):
    path = tmp_path / "big.csv"
    path.write_text("text,label\n" + "x" * 300 + ",1\n" * 900, encoding="utf-8")
    rows = preview_rows(path, "csv", limit=50)
    assert len(rows) == 50 and rows[0]["text"]


# 18: реоткрытие учёта пода не теряет накопленное
def test_budget_reopen_preserves_accrued():
    ledger = BudgetLedger()
    ledger.observe("p", 2.0, now=1_000.0, managed=True)
    ledger.mark_stopped("p", now=1_000.0 + 3600)
    ledger.observe("p", 2.0, now=1_000.0 + 3600)
    verdict = apply_guard(ledger, [], cap_usd=100.0, now=1_000.0 + 3600)
    assert verdict.spent_usd == pytest.approx(2.0)


# 20: автостоп не трогает чужие поды
def test_budget_verdict_reports_unmanaged():
    ledger = BudgetLedger()
    ledger.observe("mine", 1.0, now=0.0, managed=True)
    ledger.observe("theirs", 1.0, now=0.0)
    pods = [{"id": "mine", "desiredStatus": "RUNNING", "costPerHr": 1.0},
            {"id": "theirs", "desiredStatus": "RUNNING", "costPerHr": 1.0}]
    stopped: list[str] = []
    verdict = apply_guard(ledger, pods, cap_usd=0.5,
                          stopper=stopped.append, now=3600.0)
    assert verdict.over and verdict.spent_usd == pytest.approx(2.0)
    assert stopped == ["mine"]  # чужой под учитываем, но не трогаем


# 21: ненулевой код — не ok
def test_run_command_reports_failure(tmp_path):
    import sys
    tools = WorkspaceTools(tmp_path)
    result = tools.run_command(f'{sys.executable} -c "import sys; sys.exit(3)"')
    assert result["ok"] is False and result["returncode"] == 3
