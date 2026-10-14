"""Глубокое исправление: НАСТОЯЩИЕ прогоны классификатора и chat-template LoRA."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _tiny_base(tmp_path: Path, *, chat_template: bool = False):
    pytest.importorskip("peft")
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

    texts = ["кошка сидит на окне", "собака бежит по парку",
             "хороший добрый фильм", "плохой скучный фильм",
             "отличный вкусный обед", "ужасный холодный обед"]
    tok = Tokenizer(models.WordLevel(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.train_from_iterator(
        texts, trainers.WordLevelTrainer(special_tokens=["<unk>", "<pad>"]))
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="<unk>",
                                   pad_token="<pad>")
    if chat_template:
        fast.chat_template = (
            "{% for m in messages %}{{ m['role'] }}: {{ m['content'] }}\n"
            "{% endfor %}{% if add_generation_prompt %}assistant: {% endif %}")
    base = tmp_path / "base"
    base.mkdir()
    fast.save_pretrained(base)
    GPT2LMHeadModel(GPT2Config(
        vocab_size=len(fast), n_layer=2, n_embd=32, n_head=2,
        n_positions=128, pad_token_id=fast.pad_token_id)).save_pretrained(base)
    return base


def _run(script: Path, out: Path):
    return subprocess.run([sys.executable, str(script),
                           "--output-dir", str(out)],
                          capture_output=True, text=True, timeout=280)


def test_classifier_recipe_really_classifies(tmp_path):
    base = _tiny_base(tmp_path)
    rows = []
    for text, label in [("хороший добрый фильм", "pos"),
                        ("отличный вкусный обед", "pos"),
                        ("плохой скучный фильм", "neg"),
                        ("ужасный холодный обед", "neg")] * 4:
        rows.append({"text": text, "label": label})
    data = tmp_path / "data.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")
    from alterego_training_hub.train_script import ScriptConfig, generate_script
    cfg = ScriptConfig(path="recipe", recipe_name="classifier",
                       dataset_path=str(data), base_model=str(base),
                       epochs=1, batch=4, seq_len=32, eval_prompts=())
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = _run(script, out)
    assert done.returncode == 0, done.stderr[-500:]
    assert "Классы:" in done.stdout and "pos" in done.stdout
    assert (out / "config.json").is_file()
    import json as _json
    config = _json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert len(config.get("id2label", {})) == 2  # голова классификации, не causal LM
    assert "SequenceClassification" in str(config.get("architectures"))


def test_lora_messages_with_chat_template(tmp_path):
    base = _tiny_base(tmp_path, chat_template=True)
    rows = [{"messages": [
        {"role": "system", "content": "отвечай кратко"},
        {"role": "user", "content": "кошка сидит"},
        {"role": "assistant", "content": "на окне"}]}] * 12
    data = tmp_path / "chat.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")
    from alterego_training_hub.train_script import ScriptConfig, generate_script
    cfg = ScriptConfig(path="lora", dataset_path=str(data),
                       base_model=str(base), epochs=1, batch=4, seq_len=64,
                       eval_prompts=("кошка сидит",))
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = _run(script, out)
    assert done.returncode == 0, done.stderr[-500:]
    assert any(out.rglob("adapter_model.safetensors")) or \
        any(out.rglob("adapter_model.bin"))
