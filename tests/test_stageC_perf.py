"""Этап C: packing-изоляция, backend, group_by_length — поведение, не строки."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from alterego_training_hub.train_script import ScriptConfig, generate_script


def _gen_module(tmp_path: Path):
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(ScriptConfig(
        path="lora", dataset_path="d.txt", base_model="m",
        eval_prompts=())), encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_c", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pack_sequences_isolation(tmp_path):
    module = _gen_module(tmp_path)
    examples = [([1, 2, 3], [-100, 2, 3]),
                ([4, 5], [4, 5]),
                ([6, 7, 8, 9], [-100, -100, 8, 9])]
    packed = module._pack_sequences(examples, max_len=6, pad_id=0)
    first = packed[0]
    # границы: примеры не сливаются без маски; первый токен 2-го примера -100
    assert first["input_ids"][:5] == [1, 2, 3, 4, 5]
    assert first["labels"][3] == -100
    assert first["position_ids"][:5] == [0, 1, 2, 0, 1]  # позиции с нуля
    assert first["attention_mask"][:5] == [1] * 5
    # второй пакет: третий пример целиком, дополнен падом
    second = packed[1]
    assert second["input_ids"][:4] == [6, 7, 8, 9]
    assert second["labels"][4:] == [-100, -100]
    assert second["attention_mask"][4:] == [0, 0]


def test_packing_falls_back_without_fa2_and_training_works(tmp_path):
    pytest.importorskip("peft")
    from test_deepfix_e2e import _tiny_base

    base = _tiny_base(tmp_path)
    rows = [{"messages": [
        {"role": "user", "content": "кошка сидит"},
        {"role": "assistant", "content": "на окне"}]}] * 12
    data = tmp_path / "chat.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")
    cfg = ScriptConfig(path="lora", dataset_path=str(data),
                       base_model=str(base), epochs=1, batch=4, seq_len=64,
                       packing=True, group_by_length=True,
                       eval_prompts=("кошка сидит",))
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, str(script),
                           "--output-dir", str(out)],
                          capture_output=True, text=True, timeout=280)
    assert done.returncode == 0, done.stderr[-500:]
    # CPU: FA2 нет — packing честно отключён, обучение всё равно завершилось
    assert "packing отключён" in done.stdout
    assert any(out.rglob("adapter_model.safetensors")) or \
        any(out.rglob("adapter_model.bin"))
