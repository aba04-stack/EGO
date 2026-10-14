"""Третий аудит: РЕАЛЬНЫЕ сквозные прогоны сгенерированных скриптов.

Не проверка строк в коде: скрипты запускаются подпроцессами на настоящем
torch (и transformers/peft, если установлены). Без зависимостей — skip.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

try:
    import torch  # noqa: F401
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False

needs_torch = pytest.mark.skipif(not HAVE_TORCH, reason="нужен torch")


def _scratch_script(tmp_path: Path, dataset: Path, **over) -> Path:
    from alterego_training_hub.model_recipes import ArchPreset
    from alterego_training_hub.train_script import ScriptConfig, generate_script

    preset = ArchPreset(id="micro", name="micro", vocab=0, d_model=64,
                        layers=2, heads=2, seq_len=32)
    cfg = ScriptConfig(path="scratch", preset=preset,
                       dataset_path=str(dataset), epochs=1, batch=2,
                       seq_len=32, sample_every=10**9, **over)
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    return script


def _run(script: Path, *args, timeout=280):
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True, timeout=timeout)


LINE = "Модель учится предсказывать следующий символ этого текста. "


@needs_torch
def test_scratch_tiny_dataset_fails_fast(tmp_path):
    data = tmp_path / "tiny.txt"
    data.write_text("короткий текст\n", encoding="utf-8")
    script = _scratch_script(tmp_path, data)
    done = _run(script, "--dataset", str(data),
                "--output-dir", str(tmp_path / "o"))
    assert done.returncode != 0
    assert "слишком мал" in (done.stderr + done.stdout)


@needs_torch
def test_scratch_train_and_resume_with_changed_corpus(tmp_path):
    data = tmp_path / "data.txt"
    data.write_text((LINE * 3 + "\n") * 40, encoding="utf-8")
    script = _scratch_script(tmp_path, data)
    out1 = tmp_path / "out1"
    done = _run(script, "--output-dir", str(out1))
    assert done.returncode == 0, done.stderr[-400:]
    assert (out1 / "model.pt").is_file()
    losses = [float(p.split("=")[1]) for p in done.stdout.split()
              if p.startswith("loss=")]
    assert losses and losses[-1] < losses[0]

    changed = tmp_path / "changed.txt"
    changed.write_text(("АБВГД новый алфавит и другие слова здесь. " * 3 + "\n") * 40,
                       encoding="utf-8")
    out2 = tmp_path / "out2"
    done2 = _run(script, "--dataset", str(changed),
                 "--resume", str(out1 / "model.pt"),
                 "--output-dir", str(out2))
    assert done2.returncode == 0, done2.stderr[-400:]
    assert "словарь чекпоинта восстановлен" in done2.stdout
    assert (out2 / "model.pt").is_file()


@needs_torch
def test_scratch_torchrun_two_ranks(tmp_path):
    data = tmp_path / "data.txt"
    data.write_text((LINE * 3 + "\n") * 40, encoding="utf-8")
    script = _scratch_script(tmp_path, data)
    out = tmp_path / "ddp"
    done = subprocess.run(
        [sys.executable, "-m", "torch.distributed.run", "--standalone",
         "--nproc_per_node=2", str(script), "--output-dir", str(out)],
        capture_output=True, text=True, timeout=280)
    assert done.returncode == 0, done.stderr[-400:]
    assert (out / "model.pt").is_file()
    # Заявленные свойства DDP, а не только «не упало»: оба ранга стартовали,
    # метрики не дублируются между рангами, «Готово» печатает только главный.
    combined = done.stdout + done.stderr  # torchrun раскладывает ранги по потокам
    rank_lines = [ln for ln in combined.splitlines() if "[rank " in ln]
    assert len(rank_lines) == 2 and rank_lines[0] != rank_lines[1]
    steps = [ln.split("step=")[1].split()[0]
             for ln in done.stdout.splitlines()
             if ln.startswith("loss=")]
    assert steps and len(steps) == len(set(steps))
    assert done.stdout.count("Готово") == 1


def test_lora_real_training(tmp_path):
    pytest.importorskip("peft")
    pytest.importorskip("transformers")
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

    from alterego_training_hub.train_script import ScriptConfig, generate_script

    texts = ["кошка сидит на окне и смотрит на улицу",
             "собака бежит по парку и играет с мячом",
             "птица летит над лесом и поёт песню",
             "модель учится предсказывать следующее слово"] * 6
    tok = Tokenizer(models.WordLevel(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.train_from_iterator(
        texts, trainers.WordLevelTrainer(special_tokens=["<unk>", "<pad>"]))
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="<unk>",
                                   pad_token="<pad>")
    base = tmp_path / "base"
    base.mkdir()
    fast.save_pretrained(base)
    GPT2LMHeadModel(GPT2Config(
        vocab_size=len(fast), n_layer=2, n_embd=32, n_head=2,
        n_positions=128, pad_token_id=fast.pad_token_id)).save_pretrained(base)
    data = tmp_path / "data.txt"
    data.write_text("\n".join(texts) + "\n", encoding="utf-8")
    cfg = ScriptConfig(path="lora", dataset_path=str(data),
                       base_model=str(base), epochs=1, batch=4, seq_len=64,
                       eval_prompts=("кошка сидит",))
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    out = tmp_path / "out"
    done = _run(script, "--output-dir", str(out))
    assert done.returncode == 0, done.stderr[-500:]
    assert "val_loss=" in done.stdout  # настоящий eval, не train loss
    assert any(out.rglob("adapter_model.safetensors")) or \
        any(out.rglob("adapter_model.bin"))


def _load_generated_module(path: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_train", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@needs_torch
def test_lora_prompt_masking_helpers(tmp_path):
    """П.3: prompt маскируется -100 — проверяем ИСПОЛНЕНИЕМ сгенерированного кода."""
    data = tmp_path / "d.jsonl"
    data.write_text("{}" + chr(10), encoding="utf-8")
    script = tmp_path / "train_llm.py"
    from alterego_training_hub.train_script import ScriptConfig, generate_script
    script.write_text(generate_script(ScriptConfig(
        path="lora", dataset_path=str(data), base_model="m",
        eval_prompts=())), encoding="utf-8")
    module = _load_generated_module(script)
    assert module._mask_labels([1, 2, 3, 4], [1, 2]) == [-100, -100, 3, 4]
    assert module._mask_labels([1, 2], []) == [1, 2]
    prompt, full = module._row_pair(
        {"instruction": "Переведи", "input": "кот", "output": "cat"})
    assert prompt == "Переведи" + chr(10) + "кот"
    assert full == "Переведи" + chr(10) + "кот" + chr(10) + "cat"
    prompt, full = module._row_pair({"messages": [
        {"role": "system", "content": "Будь краток"},
        {"role": "user", "content": "Привет"},
        {"role": "assistant", "content": "Здравствуйте"}]})
    assert full.endswith("assistant: Здравствуйте")
    assert "Здравствуйте" not in prompt and "Привет" in prompt


@needs_torch
def test_scratch_resume_restores_arch(tmp_path):
    """П.8: resume со СМЕНЁННЫМ пресетом берёт архитектуру из чекпоинта."""
    from alterego_training_hub.model_recipes import ArchPreset
    from alterego_training_hub.train_script import ScriptConfig, generate_script

    data = tmp_path / "data.txt"
    data.write_text((LINE * 3 + chr(10)) * 40, encoding="utf-8")
    script = _scratch_script(tmp_path, data)
    out1 = tmp_path / "out1"
    done = _run(script, "--output-dir", str(out1))
    assert done.returncode == 0, done.stderr[-300:]

    other = ArchPreset(id="other", name="other", vocab=0, d_model=128,
                       layers=3, heads=4, seq_len=32)
    cfg = ScriptConfig(path="scratch", preset=other,
                       dataset_path=str(data), epochs=1, batch=2,
                       seq_len=32, sample_every=10**9)
    script2 = tmp_path / "train2.py"
    script2.write_text(generate_script(cfg), encoding="utf-8")
    out2 = tmp_path / "out2"
    done2 = _run(script2, "--resume", str(out1 / "model.pt"),
                 "--output-dir", str(out2))
    assert done2.returncode == 0, done2.stderr[-400:]
    assert "архитектура чекпоинта" in done2.stdout
