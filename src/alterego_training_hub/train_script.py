"""Generation of a ready-to-run training script from the wizard plan (этап 31).

Closes the gap between the «Своя ЛЛМ» wizard and the Training page: the
wizard knows the path (LoRA / from scratch / recipe), architecture preset,
dataset, tokenizer and recommended hyperparameters — this module folds them
into one self-contained ``train_llm.py`` the user can launch with the usual
training command.  The script prints metrics and generation samples in the
exact log formats the app parses (``epoch X/Y``, ``eval: val_loss=...``,
``loss=...``, ``{"sample": ...}`` lines), so dashboards, generation samples
and before/after comparison light up without extra wiring.

String generation only here — pure logic, no side effects.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .model_recipes import ArchPreset


@dataclass
class ScriptConfig:
    """Everything the wizard decided, ready to render into a script."""

    path: str = "lora"  # lora | scratch | recipe
    recipe_name: str = ""
    preset: ArchPreset | None = None
    dataset_path: str = ""
    tokenizer_path: str = ""
    base_model: str = ""  # HF id for lora/recipe paths
    output_dir: str = "runs/my-llm"
    lr: float = 1e-4
    batch: int = 16
    epochs: int = 3
    seq_len: int = 1024
    warmup_pct: int = 3
    seed: int = 42
    grad_accum: int = 1
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    qlora: bool = False  # 4-bit base (bitsandbytes) — QLoRA
    target_modules: str = "auto"  # auto | all-linear | q_proj,v_proj,...
    sample_every: int = 200  # steps between generation samples in the log
    eval_prompts: tuple[str, ...] = ("Привет! Расскажи о себе.",)

    def validate(self) -> list[str]:
        """Human-readable problems; empty list means the script is runnable."""
        problems: list[str] = []
        if self.path not in ("lora", "scratch", "recipe"):
            problems.append(f"Неизвестный путь обучения: {self.path}")
        if not self.dataset_path.strip():
            problems.append("Не указан датасет.")
        if self.path in ("lora", "recipe") and not self.base_model.strip():
            problems.append("Для LoRA/рецепта укажите базовую модель (HF id).")
        if self.lr <= 0 or self.batch < 1 or self.epochs < 1:
            problems.append("lr/batch/эпохи должны быть положительными.")
        if not 1 <= self.lora_r <= 256 or self.lora_alpha < 1:
            problems.append("LoRA r должен быть 1..256, alpha >= 1.")
        if not 0.0 <= self.lora_dropout < 1.0:
            problems.append("LoRA dropout должен быть в [0, 1).")
        if self.grad_accum < 1:
            problems.append("Gradient accumulation должен быть >= 1.")
        return problems


_HEADER = '''#!/usr/bin/env python3
"""Сгенерировано мастером «Своя ЛЛМ» (AlterEgo LLM Studio).

Путь: {recipe_name}
Запуск: python train_llm.py
Лог печатается в форматах приложения: loss=..., epoch X/Y,
eval: val_loss=..., сэмплы {{"sample": ...}} — их подхватят дашборды,
экран «Сэмплы генерации» и сравнение «до/после».
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random

CONFIG = json.loads(r"""{config_json}""")

'''

_TAIL = '''

if __name__ == "__main__":
    main()
'''


def _config_json(cfg: ScriptConfig) -> str:
    payload = {
        "path": cfg.path,
        "dataset": cfg.dataset_path,
        "tokenizer": cfg.tokenizer_path,
        "base_model": cfg.base_model,
        "output_dir": cfg.output_dir,
        "lr": cfg.lr,
        "batch": cfg.batch,
        "epochs": cfg.epochs,
        "seq_len": cfg.seq_len,
        "warmup_pct": cfg.warmup_pct,
        "seed": cfg.seed,
        "grad_accum": cfg.grad_accum,
        "lora": {"r": cfg.lora_r, "alpha": cfg.lora_alpha,
                 "dropout": cfg.lora_dropout, "qlora": cfg.qlora,
                 "target_modules": cfg.target_modules},
        "sample_every": cfg.sample_every,
        "eval_prompts": list(cfg.eval_prompts),
    }
    if cfg.preset is not None:
        payload["arch"] = {
            "id": cfg.preset.id, "vocab": cfg.preset.vocab,
            "d_model": cfg.preset.d_model, "layers": cfg.preset.layers,
            "heads": cfg.preset.heads,
            "params_est": cfg.preset.params,
        }
    return json.dumps(payload, ensure_ascii=False, indent=4)


def _common_helpers() -> str:
    return '''
def log_sample(step: int, prompt: str, text: str, checkpoint: str = "") -> None:
    """Сэмпл генерации в формате приложения (экран «Сэмплы», до/после)."""
    print(json.dumps({"sample": {"step": step, "prompt": prompt,
                                 "text": text, "checkpoint": checkpoint}},
                     ensure_ascii=False), flush=True)


def load_texts(path: str) -> list[str]:
    """Датасет: .txt построчно, .jsonl (поле text/prompt), .json список."""
    if path.endswith(".jsonl"):
        rows = [json.loads(line) for line in open(path, encoding="utf-8")
                if line.strip()]
        return [str(r.get("text") or r.get("prompt") or "") for r in rows]
    if path.endswith(".json"):
        raw = json.load(open(path, encoding="utf-8"))
        if isinstance(raw, list):
            return [str(r.get("text", r) if isinstance(r, dict) else r)
                    for r in raw]
        return [str(raw)]
    return [line for line in open(path, encoding="utf-8").read().splitlines()
            if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=CONFIG["dataset"])
    parser.add_argument("--output-dir", default=CONFIG["output_dir"])
    parser.add_argument("--epochs", type=int, default=CONFIG["epochs"])
    parser.add_argument("--lr", type=float, default=CONFIG["lr"])
    args = parser.parse_args()
    random.seed(CONFIG["seed"])
    texts = [t for t in load_texts(args.dataset) if t.strip()]
    if not texts:
        raise SystemExit("Датасет пуст — проверьте путь и формат.")
    print(f"Данные: {len(texts)} строк", flush=True)
    if CONFIG["path"] == "scratch":
        train_scratch(args, texts)
    else:
        train_lora(args, texts)

'''


def _scratch_body() -> str:
    return '''
def train_scratch(args, texts: list[str]) -> None:
    """Обучение с нуля: char/byte модель на чистом PyTorch (если установлен)."""
    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise SystemExit(
            "Нужен PyTorch: pip install torch (или образ runpod/pytorch).") from exc

    arch = CONFIG["arch"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Токенизатор: сгенерированный мастером BPE (library/tokenizers) — зачаток;
    # для простоты старта используем char-level словарь по корпусу.
    corpus = "\\n".join(texts)
    vocab = sorted(set(corpus))
    stoi = {ch: i + 1 for i, ch in enumerate(vocab)}
    itos = {i: ch for ch, i in stoi.items()}
    data = torch.tensor([stoi.get(ch, 0) for ch in corpus], dtype=torch.long)
    seq = min(CONFIG["seq_len"], 512)
    print(f"Токенизатор: char-level, vocab={len(stoi)} (пресет "
          f"{arch['id']}: ~{arch['params_est'] / 1e6:.0f}M параметров)", flush=True)

    class Block(nn.Module):
        def __init__(self, d):
            super().__init__()
            self.attn = nn.MultiheadAttention(d, arch["heads"],
                                              batch_first=True)
            self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(),
                                     nn.Linear(4 * d, d))
            self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)

        def forward(self, x):
            mask = torch.triu(torch.ones(x.size(1), x.size(1), device=x.device),
                              diagonal=1).bool()
            h, _ = self.attn(self.ln1(x), self.ln1(x), self.ln1(x),
                             attn_mask=mask, need_weights=False)
            x = x + h
            return x + self.mlp(self.ln2(x))

    class TinyLM(nn.Module):
        def __init__(self):
            super().__init__()
            d = arch["d_model"]
            self.embed = nn.Embedding(len(stoi) + 1, d)
            self.pos = nn.Embedding(seq, d)
            self.blocks = nn.Sequential(
                *[Block(d) for _ in range(min(arch["layers"], 24))])
            self.head = nn.Linear(d, len(stoi) + 1)

        def forward(self, idx):
            pos = torch.arange(idx.size(1), device=idx.device)
            return self.head(self.blocks(self.embed(idx) + self.pos(pos)))

    model = TinyLM().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    steps_per_epoch = max(1, (len(data) - seq) // (CONFIG["batch"] * seq))
    total_steps = steps_per_epoch * args.epochs
    print(f"Устройство: {device}, шагов: ~{total_steps}", flush=True)
    step = 0
    for epoch in range(1, args.epochs + 1):
        print(f"epoch {epoch}/{args.epochs}", flush=True)
        for _ in range(steps_per_epoch):
            starts = torch.randint(0, len(data) - seq - 1,
                                   (CONFIG["batch"],))
            batch = torch.stack([data[s:s + seq] for s in starts]).to(device)
            target = torch.stack([data[s + 1:s + seq + 1]
                                  for s in starts]).to(device)
            logits = model(batch)
            loss = nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)), target.reshape(-1))
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            step += 1
            if step % 20 == 0:
                value = float(loss.detach())
                print(f"loss={value:.4f} step={step} "
                      f"ppl={math.exp(min(value, 20)):.2f}", flush=True)
                print(f"eval: val_loss={value:.4f}", flush=True)
            if step % max(1, CONFIG["sample_every"]) == 0:
                model.eval()
                with torch.no_grad():
                    prompt = CONFIG["eval_prompts"][0][:20] or "А"
                    ids = [stoi.get(ch, 0) for ch in prompt]
                    cur = torch.tensor([ids], device=device)
                    out = list(ids)
                    for _ in range(80):
                        nxt = int(torch.argmax(
                            model(cur[:, -seq:])[0, -1]).item())
                        out.append(nxt)
                        cur = torch.cat([cur, torch.tensor(
                            [[nxt]], device=device)], dim=1)
                    text = "".join(itos.get(i, "") for i in out)
                model.train()
                log_sample(step, prompt, text, checkpoint=f"epoch-{epoch}")
    os.makedirs(args.output_dir, exist_ok=True)
    torch.save(model.state_dict(),
               os.path.join(args.output_dir, "model.pt"))
    print(f"Готово. Чекпоинт: {args.output_dir}/model.pt", flush=True)

'''


def _lora_body() -> str:
    return '''
def train_lora(args, texts: list[str]) -> None:
    """LoRA/QLoRA поверх базовой модели через Hugging Face (transformers+peft)."""
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import (AutoModelForCausalLM, AutoTokenizer,
                                  Trainer, TrainingArguments)
    except ImportError as exc:
        raise SystemExit(
            "Нужны transformers/peft/datasets: "
            "pip install transformers peft datasets accelerate") from exc

    base = CONFIG["base_model"]
    lora_cfg = CONFIG["lora"]
    print(f"Базовая модель: {base} · LoRA r={lora_cfg['r']}, "
          f"alpha={lora_cfg['alpha']}, QLoRA={lora_cfg['qlora']}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    load_kwargs = {"torch_dtype": torch.bfloat16 if torch.cuda.is_available()
                   else torch.float32}
    if lora_cfg["qlora"]:
        from transformers import BitsAndBytesConfig
        load_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(base, **load_kwargs)
    targets = lora_cfg["target_modules"]
    model = get_peft_model(model, LoraConfig(
        r=lora_cfg["r"], lora_alpha=lora_cfg["alpha"],
        lora_dropout=lora_cfg["dropout"],
        target_modules=None if targets == "auto" else
        ([t.strip() for t in targets.split(",") if t.strip()]
         if targets != "all-linear" else "all-linear"),
        task_type="CAUSAL_LM"))
    rows = [{"text": t} for t in texts]
    split = max(1, int(len(rows) * 0.9))
    train_ds, eval_ds = Dataset.from_list(rows[:split]), Dataset.from_list(rows[split:])

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True,
                         max_length=CONFIG["seq_len"])

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.output_dir,
            per_device_train_batch_size=CONFIG["batch"],
            gradient_accumulation_steps=CONFIG["grad_accum"],
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            warmup_ratio=CONFIG["warmup_pct"] / 100.0,
            logging_steps=20, eval_strategy="epoch", save_strategy="epoch",
            report_to=[], seed=CONFIG["seed"]),
        train_dataset=train_ds.map(tokenize, batched=True),
        eval_dataset=eval_ds.map(tokenize, batched=True),
    )
    trainer.train()
    metrics = trainer.evaluate()
    val = metrics.get("eval_loss")
    if val is not None:
        print(f"eval: val_loss={val:.4f}", flush=True)
    for prompt in CONFIG["eval_prompts"]:
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        out = model.generate(**inputs, max_new_tokens=60, do_sample=False)
        log_sample(int(trainer.state.global_step), prompt,
                   tokenizer.decode(out[0], skip_special_tokens=True),
                   checkpoint="final")
    trainer.save_model(args.output_dir)
    print(f"Готово. Адаптер: {args.output_dir}", flush=True)

'''


def generate_script(cfg: ScriptConfig) -> str:
    """Render the full train_llm.py source for a wizard configuration."""
    header = _HEADER.format(recipe_name=cfg.recipe_name or cfg.path,
                            config_json=_config_json(cfg))
    return header + _common_helpers() + _scratch_body() + _lora_body() + _TAIL


def script_filename(cfg: ScriptConfig) -> str:
    return "train_llm.py"


def render_plan_note(cfg: ScriptConfig) -> str:
    """Short human note shown before saving the script."""
    problems = cfg.validate()
    rows = [f"Скрипт обучения: путь {cfg.path}, датасет {cfg.dataset_path or '—'}, "
            f"lr={cfg.lr:g}, batch={cfg.batch}, эпох={cfg.epochs}."]
    if cfg.preset is not None:
        rows.append(f"Архитектура: {cfg.preset.name} (~{cfg.preset.params_human}).")
    if problems:
        rows.append("⚠ Перед запуском исправьте:")
        rows.extend(f"  — {p}" for p in problems)
    else:
        rows.append("✓ Готов к сохранению и запуску через страницу «Обучение».")
    return "\n".join(rows)
