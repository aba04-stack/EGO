"""Этап E: DPO — реальный прогон, метрики предпочтений, честные отказы."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from alterego_training_hub.train_script import ScriptConfig, generate_script


def _pairs(tmp_path: Path, n: int = 16) -> Path:
    data = tmp_path / "prefs.jsonl"
    rows = [{"prompt": f"назови цвет {i}",
             "chosen": f"синий {i}", "rejected": f"банан {i}"}
            for i in range(n)]
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")
    return data


def test_dpo_too_few_pairs_refused(tmp_path):
    cfg = ScriptConfig(path="lora", recipe_name="dpo",
                       dataset_path=str(_pairs(tmp_path, 2)),
                       base_model="m", eval_prompts=())
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    done = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode != 0
    assert "минимум 4 пары" in (done.stdout + done.stderr)


def test_dpo_real_run_reports_preference_metrics(tmp_path):
    pytest.importorskip("trl")
    from test_deepfix_e2e import _tiny_base

    cfg = ScriptConfig(path="lora", recipe_name="dpo",
                       dataset_path=str(_pairs(tmp_path)),
                       base_model=str(_tiny_base(tmp_path)), epochs=1,
                       batch=4, seq_len=64, lr=5e-4,
                       eval_prompts=("назови цвет 1",))
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, str(script),
                           "--output-dir", str(out)],
                          capture_output=True, text=True, timeout=280)
    assert done.returncode == 0, done.stderr[-600:]
    assert "DPO до: acc_logp=" in done.stdout
    assert "DPO после: acc_logp=" in done.stdout
    assert "[DPO до]" in done.stdout and "[DPO после]" in done.stdout
    record = json.loads((out / "run-record.json").read_text("utf-8"))
    assert "pref_acc_before" in record["metrics"]
    assert "pref_acc_after" in record["metrics"]
    assert any(out.rglob("adapter_model.safetensors")) or \
        any(out.rglob("adapter_model.bin"))
