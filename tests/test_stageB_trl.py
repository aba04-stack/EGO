"""Этап B: TRL-путь — разрешение движка, честные отказы, реальное обучение."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from alterego_training_hub.train_script import (
    ScriptConfig,
    effective_engine,
    generate_script,
)


def test_engine_resolution():
    assert effective_engine(ScriptConfig(engine="trainer",
                                         recipe_name="chatbot")) == "trainer"
    assert effective_engine(ScriptConfig(engine="trl")) == "trl"
    # auto: trl только для чат-рецепта и при установленном trl
    import importlib.util as _iu
    expected = "trl" if _iu.find_spec("trl") else "trainer"
    assert effective_engine(ScriptConfig(engine="auto",
                                         recipe_name="chatbot")) == expected
    assert effective_engine(ScriptConfig(engine="auto",
                                         recipe_name="code")) == "trainer"
    code = generate_script(ScriptConfig(path="lora", engine="trl",
                                        dataset_path="d.txt",
                                        base_model="m"))
    compile(code, "train_llm.py", "exec")
    assert "train_lora_trl" in code


def test_trl_resume_refused_honestly(tmp_path):
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(ScriptConfig(
        path="lora", engine="trl", dataset_path="d.txt", base_model="m",
        eval_prompts=())), encoding="utf-8")
    done = subprocess.run([sys.executable, str(script), "--resume", "x"],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode != 0
    assert "resume не поддержан" in (done.stdout + done.stderr)


def test_trl_real_training(tmp_path):
    pytest.importorskip("trl")
    from test_deepfix_e2e import _tiny_base

    base = _tiny_base(tmp_path)
    rows = [{"messages": [
        {"role": "user", "content": "кошка сидит"},
        {"role": "assistant", "content": "на окне"}]}] * 12
    data = tmp_path / "chat.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")
    cfg = ScriptConfig(path="lora", engine="trl", dataset_path=str(data),
                       base_model=str(base), epochs=1, batch=4, seq_len=64,
                       eval_prompts=("кошка сидит",))
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, str(script),
                           "--output-dir", str(out)],
                          capture_output=True, text=True, timeout=280)
    assert done.returncode == 0, done.stderr[-500:]
    assert "Движок: TRL SFTTrainer" in done.stdout
    assert any(out.rglob("adapter_model.safetensors")) or \
        any(out.rglob("adapter_model.bin"))
