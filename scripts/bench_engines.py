#!/usr/bin/env python3
"""Этап A: паритетный стенд движков обучения (наш Trainer vs TRL SFTTrainer).

Одинаковые: исходные веса, токенизатор, датасет (prompt/completion),
маски (loss только по completion), validation-сплит (seed 42, 10%),
целевые токены, LoRA-конфиг. Качество синтетики НЕ обобщается — это
стенд throughput и сопоставимости, а не доказательство «ума» модели.

Запуск: .venv/bin/python scripts/bench_engines.py [--work DIR] [--examples 512]
Результаты: <work>/results.json + stdout-таблица.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

WORDS = ["кошка", "собака", "птица", "модель", "данные", "обучение", "сеть", "токен", "пример", "вопрос", "ответ", "текст", "слово", "код", "файл", "сервер"]
SEED = 42

_LAUNCHER = r"""
import resource, subprocess, sys, time, json
start = time.time()
done = subprocess.run(sys.argv[1:])
wall = time.time() - start
peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0
print(json.dumps({"__bench__": {"wall_s": round(wall, 2),
                                "peak_rss_mb": round(peak, 1),
                                "returncode": done.returncode}}))
sys.exit(done.returncode)
"""


def build_dataset(work: Path, n: int) -> Path:
    rng = random.Random(SEED)
    rows = []
    for i in range(n):
        phrase = " ".join(rng.choices(WORDS, k=rng.randint(3, 9)))
        answer = " ".join(rng.choices(WORDS, k=rng.randint(3, 7)))
        rows.append({"messages": [
            {"role": "user", "content": f"Вопрос {i}: {phrase}"},
            {"role": "assistant", "content": f"Ответ: {answer}."}]})
    path = work / "data.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in rows), encoding="utf-8")
    return path


def build_base(work: Path, data_rows: list[dict]) -> Path:
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

    texts = [" ".join(m["content"] for m in r["messages"])
             for r in data_rows]
    tok = Tokenizer(models.WordLevel(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.train_from_iterator(texts, trainers.WordLevelTrainer(
        special_tokens=["<unk>", "<pad>"]))
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="<unk>",
                                   pad_token="<pad>")
    # Один chat template для обоих движков — паритет рендера и масок.
    fast.chat_template = (
        "{% for m in messages %}{{ m['role'] }}: {{ m['content'] }}\n"
        "{% endfor %}{% if add_generation_prompt %}assistant: {% endif %}")
    base = work / "base"
    base.mkdir(exist_ok=True)
    fast.save_pretrained(base)
    GPT2LMHeadModel(GPT2Config(
        vocab_size=len(fast), n_layer=2, n_embd=32, n_head=2,
        n_positions=128, pad_token_id=fast.pad_token_id)).save_pretrained(base)
    return base


def launch(cmd: list[str], log: Path) -> dict:
    done = subprocess.run([sys.executable, "-c", _LAUNCHER, *cmd],
                          capture_output=True, text=True, timeout=1200)
    log.write_text(done.stdout + "\n--- STDERR ---\n" + done.stderr,
                   encoding="utf-8")
    info = {"returncode": done.returncode}
    for line in done.stdout.splitlines():
        if '"__bench__"' in line:
            info.update(json.loads(line)["__bench__"])
    return info


_TRL_RUNNER = r'''
import json, sys
from datasets import Dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer

work, base, out = sys.argv[1], sys.argv[2], sys.argv[3]
rows = [json.loads(ln) for ln in open(work + "/data.jsonl", encoding="utf-8")]
ds = Dataset.from_list(rows)
parts = ds.train_test_split(test_size=max(1, len(rows) // 10), seed=42)
trainer = SFTTrainer(
    model=base,
    args=SFTConfig(output_dir=out, per_device_train_batch_size=4,
                   num_train_epochs=1, learning_rate=1e-4,
                   lr_scheduler_type="cosine", warmup_ratio=0.03,
                   max_seq_length=64, packing=False, report_to=[], seed=42),
    train_dataset=parts["train"], eval_dataset=parts["test"],
    peft_config=LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                           target_modules=["c_attn"], task_type="CAUSAL_LM"))
trainer.train()
metrics = trainer.evaluate()
print(f"eval: val_loss={metrics['eval_loss']:.4f}", flush=True)
trainer.save_model(out)
'''

_EVAL = r'''
import json, sys
import torch
from datasets import Dataset
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

work, base, adapter = sys.argv[1], sys.argv[2], sys.argv[3]
tok = AutoTokenizer.from_pretrained(base)
rows = [json.loads(ln) for ln in open(work + "/data.jsonl", encoding="utf-8")]
parts = Dataset.from_list(rows).train_test_split(
    test_size=max(1, len(rows) // 10), seed=42)
model = AutoModelForCausalLM.from_pretrained(base)
model = PeftModel.from_pretrained(model, adapter)
model.eval()
losses, target_tokens = [], 0
for row in parts["test"]:
    msgs = row["messages"]
    full = tok.apply_chat_template(msgs, tokenize=True,
                                   return_tensors="pt")
    prompt_len = len(tok.apply_chat_template(
        msgs[:1], tokenize=True, add_generation_prompt=True))
    full = {"input_ids": full}
    labels = full["input_ids"].clone()
    labels[:, :prompt_len] = -100
    target_tokens += int((labels != -100).sum())
    with torch.no_grad():
        losses.append(float(model(**full, labels=labels).loss))
print(json.dumps({"val_loss_masked": round(sum(losses) / len(losses), 4),
                  "val_examples": len(losses),
                  "val_target_tokens": target_tokens}))
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", default="/tmp/alterego-bench-a")
    parser.add_argument("--examples", type=int, default=512)
    args = parser.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(ln) for ln in
            build_dataset(work, args.examples).read_text(
                encoding="utf-8").splitlines()]
    base = build_base(work, rows)

    from alterego_training_hub.train_script import ScriptConfig, generate_script

    ours = work / "ours_train.py"
    ours.write_text(generate_script(ScriptConfig(
        path="lora", dataset_path=str(work / "data.jsonl"),
        base_model=str(base), epochs=1, batch=4, seq_len=64,
        lora_r=16, lora_alpha=32, target_modules="c_attn",
        eval_prompts=("Вопрос 0:",))), encoding="utf-8")
    trl_script = work / "trl_train.py"
    trl_script.write_text(_TRL_RUNNER, encoding="utf-8")
    eval_script = work / "eval_adapter.py"
    eval_script.write_text(_EVAL, encoding="utf-8")

    results: dict = {"seed": SEED, "examples": len(rows), "engines": {}}
    engines = {
        "ours": [sys.executable, str(ours), "--output-dir", str(work / "out_ours")],
        "trl": [sys.executable, str(trl_script), str(work), str(base),
                str(work / "out_trl")],
    }
    for name, cmd in engines.items():
        info = launch(cmd, work / f"{name}.log")
        entry = {**info, "cmd": " ".join(cmd)}
        out_dir = work / ("out_ours" if name == "ours" else "out_trl")
        if info.get("returncode") == 0:
            ev = subprocess.run(
                [sys.executable, str(eval_script), str(work), str(base),
                 str(out_dir)], capture_output=True, text=True, timeout=600)
            for line in ev.stdout.splitlines():
                if line.startswith("{"):
                    entry["eval"] = json.loads(line)
        results["engines"][name] = entry
        print(f"{name}: {entry}")

    (work / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("\nИтог:")
    for name, entry in results["engines"].items():
        ev = entry.get("eval", {})
        print(f"  {name}: wall={entry.get('wall_s')}s "
              f"rss={entry.get('peak_rss_mb')}MB rc={entry.get('returncode')} "
              f"val_loss={ev.get('val_loss_masked')}")
    return 0 if all(e.get("returncode") == 0
                    for e in results["engines"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
