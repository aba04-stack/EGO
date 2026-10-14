"""Этап 44: бюджетный страж, multi-GPU скрипт, VRAM в логе."""
import time

from alterego_training_hub.budget_guard import BudgetLedger, check_budget
from alterego_training_hub.train_script import (
    ScriptConfig,
    distributed_launch_command,
    generate_script,
)


def test_ledger_accrues_and_autostops(tmp_path):
    ledger = BudgetLedger.load(tmp_path / "budget.json")
    now = time.time()
    ledger.observe("pod-1", 2.0, now=now - 3600, managed=True)  # 1 hour at $2/h
    verdict = check_budget(ledger, cap_usd=1.0, now=now)
    assert verdict.spent_usd >= 1.99 and verdict.over
    stopped = []
    verdict = check_budget(ledger, cap_usd=1.0,
                           stopper=stopped.append, now=now)
    assert stopped == ["pod-1"] and verdict.stopped == ["pod-1"]
    ledger.save()
    reloaded = BudgetLedger.load(tmp_path / "budget.json")
    assert reloaded.pods["pod-1"].stopped_at == now


def test_no_cap_no_stop(tmp_path):
    ledger = BudgetLedger.load(tmp_path / "b.json")
    ledger.observe("p", 5.0, now=time.time() - 7200, managed=True)
    verdict = check_budget(ledger, cap_usd=0.0,
                           stopper=lambda pid: (_ for _ in ()).throw(
                               AssertionError("no stop without cap")))
    assert not verdict.over and "не задан" in verdict.render()


def test_multi_gpu_script():
    cfg = ScriptConfig(path="lora", dataset_path="d.txt", base_model="m",
                       gpus=4, grad_accum=2)
    code = generate_script(cfg)
    assert '"gpus": 4' in code and "torchrun" in code
    assert "ddp_find_unused_parameters" in code
    assert distributed_launch_command(cfg).startswith("torchrun")
    assert distributed_launch_command(
        ScriptConfig(path="lora", dataset_path="d", base_model="m")
    ) == "python train_llm.py"
    assert cfg.validate() == []
    bad = ScriptConfig(path="lora", dataset_path="d", base_model="m",
                       gpus=0)
    assert any("GPU" in p for p in bad.validate())
    compile(code, "train_llm.py", "exec")


def test_vram_logged_in_scratch():
    code = generate_script(ScriptConfig(path="scratch", dataset_path="d"))
    assert "max_memory_allocated" in code
