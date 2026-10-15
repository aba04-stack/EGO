"""Этап D: run-record v2 — реальный прогон, хэши, импорт в историю."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from alterego_training_hub.run_record import (
    load_run_record,
    record_artifacts_ok,
    to_run_record,
)
from alterego_training_hub.train_script import ScriptConfig, generate_script


def _chat(tmp_path: Path) -> Path:
    rows = [{"messages": [
        {"role": "user", "content": "кошка сидит"},
        {"role": "assistant", "content": "на окне"}]}] * 12
    data = tmp_path / "chat.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")
    return data


def test_run_record_written_and_importable(tmp_path):
    pytest.importorskip("peft")
    from test_deepfix_e2e import _tiny_base

    data = _chat(tmp_path)
    cfg = ScriptConfig(path="lora", dataset_path=str(data),
                       base_model=str(_tiny_base(tmp_path)), epochs=1,
                       batch=4, seq_len=64, eval_prompts=("кошка сидит",))
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, str(script),
                           "--output-dir", str(out)],
                          capture_output=True, text=True, timeout=280)
    assert done.returncode == 0, done.stderr[-400:]
    record_path = out / "run-record.json"
    assert record_path.exists(), done.stdout[-400:]
    record = load_run_record(record_path)
    assert record["status"] == "success"
    assert record["dataset"]["sha256"] == hashlib.sha256(
        data.read_bytes()).hexdigest()
    assert record["versions"]["peft"]  # версии зафиксированы по факту
    assert record_artifacts_ok(record, out) == []
    run = to_run_record(record, record_path)
    assert run.returncode == 0
    assert run.environment["dataset_sha256"] == record["dataset"]["sha256"]


def test_failed_run_still_records(tmp_path):
    pytest.importorskip("trl")
    cfg = ScriptConfig(path="lora", engine="trl", dataset_path="d.txt",
                       base_model="m", eval_prompts=())
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, str(script), "--resume", "x",
                           "--output-dir", str(out)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode != 0
    record = load_run_record(out / "run-record.json")
    assert record["status"] == "failed"
    assert "resume" in record["error"]


def test_load_rejects_foreign_json(tmp_path):
    bad = tmp_path / "run-record.json"
    bad.write_text('{"schema": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_run_record(bad)
