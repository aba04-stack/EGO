"""Этап 31: генерация train_llm.py из плана мастера."""
import ast

from alterego_training_hub.model_recipes import get_preset
from alterego_training_hub.train_script import (
    ScriptConfig,
    generate_script,
    render_plan_note,
    script_filename,
)


def _cfg(**over) -> ScriptConfig:
    base = dict(path="scratch", recipe_name="Обучить с нуля",
                preset=get_preset("gpt2-small"), dataset_path="data.txt",
                lr=3e-4, batch=32, epochs=1, seq_len=512)
    base.update(over)
    return ScriptConfig(**base)


def test_generated_script_is_valid_python_with_formats():
    code = generate_script(_cfg())
    ast.parse(code)  # синтаксис валиден
    assert '"path": "scratch"' in code
    assert "eval: val_loss=" in code  # формат для evaluation/build_eval_report
    assert '{"sample":' in code       # формат для gen_preview.parse_samples
    assert "epoch {epoch}/" in code or "epoch " in code
    assert "params_est" in code  # оценка параметров пресета попала в конфиг


def test_lora_script_mentions_base_and_peft():
    code = generate_script(_cfg(path="lora", base_model="meta-llama/x"))
    assert "meta-llama/x" in code and "LoraConfig" in code
    assert '"r": 16' in code and "lora_cfg" in code


def test_validation_and_note():
    bad = _cfg(dataset_path="", path="lora", base_model="")
    problems = bad.validate()
    assert any("датасет" in p for p in problems)
    assert any("базовую модель" in p for p in problems)
    note = render_plan_note(bad)
    assert "⚠" in note
    good = render_plan_note(_cfg())
    assert "✓ Готов" in good


def test_script_filename():
    assert script_filename(_cfg()) == "train_llm.py"
