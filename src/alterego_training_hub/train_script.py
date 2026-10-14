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
    gpus: int = 1  # >1 — torchrun/DDP
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
        if not 1 <= self.gpus <= 64:
            problems.append("Число GPU должно быть 1..64.")
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
        "gpus": cfg.gpus,
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


def _row_text(row) -> str:
    """Текст строки датасета: text/prompt, instruction+output, messages."""
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return str(row or "")
    messages = row.get("messages")
    if isinstance(messages, list):
        return "\\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in messages if isinstance(m, dict) and m.get("content"))
    text = str(row.get("text") or row.get("prompt")
               or row.get("instruction") or "")
    answer = str(row.get("output") or row.get("completion")
                 or row.get("response") or "")
    return f"{text}\\n{answer}" if answer else text


def load_texts(path: str) -> list[str]:
    """Датасет построчно (стриминг): .txt, .jsonl, .json список.

    Битые JSON-строки пропускаются с предупреждением, а не роняют
    загрузку на середине файла.
    """
    if path.endswith(".jsonl"):
        texts, bad = [], 0
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    texts.append(_row_text(json.loads(line)))
                except json.JSONDecodeError:
                    bad += 1
        if bad:
            print(f"⚠ Пропущено битых JSON-строк: {bad}", flush=True)
        return texts
    if path.endswith(".json"):
        raw = json.load(open(path, encoding="utf-8"))
        if isinstance(raw, list):
            return [_row_text(row) for row in raw]
        return [_row_text(raw)]
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip("\\n") for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=CONFIG["dataset"])
    parser.add_argument("--output-dir", default=CONFIG["output_dir"])
    parser.add_argument("--epochs", type=int, default=CONFIG["epochs"])
    parser.add_argument("--lr", type=float, default=CONFIG["lr"])
    parser.add_argument("--resume", default="",
                        help="чекпоинт для продолжения обучения")
    args = parser.parse_args()
    random.seed(CONFIG["seed"])
    if CONFIG["gpus"] > 1 and "LOCAL_RANK" not in os.environ:
        print(f"Подсказка: для {CONFIG['gpus']} GPU запустите через "
              f"torchrun --nproc_per_node={CONFIG['gpus']} train_llm.py",
              flush=True)
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
    # Распределённый запуск (torchrun): каждый процесс — своё устройство
    # и свой сэмплер; без этого DDP обучал бы все ранги на одном GPU
    # одними и теми же батчами.
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    world = int(os.environ.get("WORLD_SIZE", "1"))
    distributed = world > 1
    if distributed:
        import torch.distributed as dist
        dist.init_process_group(
            "nccl" if torch.cuda.is_available() else "gloo")
        if torch.cuda.is_available():
            torch.cuda.set_device(local_rank)
            device = f"cuda:{local_rank}"
        else:
            device = "cpu"
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    main_proc = rank == 0
    # Токенизатор: сгенерированный мастером BPE (library/tokenizers) — зачаток;
    # для простоты старта используем char-level словарь по корпусу.
    corpus = "\\n".join(texts)
    vocab = sorted(set(corpus))
    stoi = {ch: i + 1 for i, ch in enumerate(vocab)}
    itos = {i: ch for ch, i in stoi.items()}
    # Resume: словарь берём из бандла чекпоинта, а не из текущего корпуса —
    # иначе при изменившемся корпусе размеры эмбеддингов не совпадут
    # и веса либо не загрузятся, либо лягут не на те символы.
    resume_bundle = None
    if args.resume and os.path.isfile(args.resume):
        loaded = torch.load(args.resume, map_location="cpu")
        if isinstance(loaded, dict) and isinstance(loaded.get("stoi"), dict):
            resume_bundle = loaded
            stoi = {str(ch): int(i) for ch, i in loaded["stoi"].items()}
            itos = {int(i): str(ch) for ch, i in stoi.items()}
            if main_proc:
                print(f"Resume: словарь чекпоинта восстановлен "
                      f"(vocab={len(stoi)})", flush=True)
        elif isinstance(loaded, dict) and "state_dict" in loaded:
            resume_bundle = loaded
    data = torch.tensor([stoi.get(ch, 0) for ch in corpus], dtype=torch.long)
    seq = min(CONFIG["seq_len"], 1024)  # char-модель: предел по памяти позиций
    min_tokens = 4 * seq + 8
    if len(data) < min_tokens:
        raise SystemExit(
            f"Датасет слишком мал для scratch: {len(data)} токенов, нужно "
            f">= {min_tokens} при seq_len={seq} (train и val должны быть "
            "разными и длиннее последовательности). Уменьшите seq_len "
            "в мастере или добавьте данных.")
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

    # Честный val: последние 10% токенов не участвуют в обучении.
    n_val = max(seq + 2, len(data) // 10)
    train_data, val_data = (data[:-n_val], data[-n_val:]) \
        if len(data) > 2 * seq else (data, data)
    model = TinyLM().to(device)
    if distributed:
        model = nn.parallel.DistributedDataParallel(
            model,
            device_ids=[local_rank] if torch.cuda.is_available() else None)
    if args.resume and os.path.isfile(args.resume):
        bundle = resume_bundle
        if bundle is None:
            bundle = torch.load(args.resume, map_location="cpu")
        state = bundle.get("state_dict", bundle) \
            if isinstance(bundle, dict) else bundle
        raw = model.module if hasattr(model, "module") else model
        raw.load_state_dict(state)
        if main_proc:
            print(f"Resume: веса из {args.resume} "
                  "(оптимизатор и шаг начнутся заново)", flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)

    def _bundle():
        """Чекпоинт для самостоятельного восстановления: веса+словарь+конфиг."""
        raw_model = model.module if hasattr(model, "module") else model
        return {"state_dict": raw_model.state_dict(), "stoi": stoi,
                "itos": {str(k): v for k, v in itos.items()},
                "arch": arch, "seq": seq,
                "config": {"seq_len": CONFIG["seq_len"],
                           "lr": args.lr, "epochs": args.epochs}}
    steps_per_epoch = max(1, (len(train_data) - seq) // (CONFIG["batch"] * seq))
    accum = max(1, CONFIG["grad_accum"])

    def batch_from(source, step_no=0):
        if len(source) <= seq + 1:
            raise SystemExit(
                f"Выборка слишком коротка для батчей: {len(source)} токенов "
                f"при seq={seq}.")
        gen = torch.Generator().manual_seed(
            1234 + step_no * max(1, world) + rank)
        starts = torch.randint(0, len(source) - seq - 1,
                               (CONFIG["batch"],), generator=gen)
        x = torch.stack([source[i:i + seq] for i in starts]).to(device)
        y = torch.stack([source[i + 1:i + seq + 1] for i in starts]).to(device)
        return x, y
    total_steps = steps_per_epoch * args.epochs
    print(f"Устройство: {device}, шагов: ~{total_steps}", flush=True)
    step = 0
    for epoch in range(1, args.epochs + 1):
        print(f"epoch {epoch}/{args.epochs}", flush=True)
        for _ in range(steps_per_epoch):
            opt.zero_grad()
            value = 0.0
            for _micro in range(accum):
                batch, target = batch_from(train_data, step)
                logits = model(batch)
                loss = nn.functional.cross_entropy(
                    logits.reshape(-1, logits.size(-1)),
                    target.reshape(-1)) / accum
                loss.backward()
                value = float(loss.detach()) * accum
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            step += 1
            if step % 20 == 0:
                mem = (f" mem={torch.cuda.max_memory_allocated() / 1e9:.2f}GB"
                       if torch.cuda.is_available() else "")
                print(f"loss={value:.4f} step={step} "
                      f"ppl={math.exp(min(value, 20)):.2f}{mem}", flush=True)
                model.eval()
                with torch.no_grad():
                    val_losses = []
                    for _v in range(4):
                        vx, vy = batch_from(val_data)
                        vlogits = model(vx)
                        val_losses.append(float(nn.functional.cross_entropy(
                            vlogits.reshape(-1, vlogits.size(-1)),
                            vy.reshape(-1))))
                model.train()
                print(f"eval: val_loss={sum(val_losses) / len(val_losses):.4f}",
                      flush=True)
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
        if main_proc:
            os.makedirs(args.output_dir, exist_ok=True)
            torch.save(_bundle(), os.path.join(
                args.output_dir, f"checkpoint-epoch{epoch}.pt"))
    if main_proc:
        torch.save(_bundle(), os.path.join(args.output_dir, "model.pt"))
        print(f"Готово. Чекпоинт: {args.output_dir}/model.pt", flush=True)
    if distributed:
        import torch.distributed as dist
        dist.destroy_process_group()

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
                                  DataCollatorForSeq2Seq, Trainer,
                                  TrainingArguments)
    except ImportError as exc:
        raise SystemExit(
            "Нужны transformers/peft/datasets: "
            "pip install transformers peft datasets accelerate") from exc

    base = CONFIG["base_model"]
    lora_cfg = CONFIG["lora"]
    print(f"Базовая модель: {base} · LoRA r={lora_cfg['r']}, "
          f"alpha={lora_cfg['alpha']}, QLoRA={lora_cfg['qlora']}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(CONFIG["tokenizer"] or base)
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
    if args.resume and os.path.isdir(args.resume) and os.path.exists(
            os.path.join(args.resume, "adapter_config.json")):
        from peft import PeftModel
        print(f"Resume: адаптер из {args.resume} "
              "(веса адаптера; оптимизатор начнётся заново)", flush=True)
        model = PeftModel.from_pretrained(model, args.resume,
                                          is_trainable=True)
        targets = None
    else:
        targets = lora_cfg["target_modules"]
    if targets is not None or not args.resume:
        model = get_peft_model(model, LoraConfig(
        r=lora_cfg["r"], lora_alpha=lora_cfg["alpha"],
        lora_dropout=lora_cfg["dropout"],
        target_modules=None if targets == "auto" else
        ([t.strip() for t in targets.split(",") if t.strip()]
         if targets != "all-linear" else "all-linear"),
        task_type="CAUSAL_LM"))
    rows = [{"text": t} for t in texts]
    random.Random(CONFIG["seed"]).shuffle(rows)
    if len(rows) >= 2:
        split = max(1, len(rows) - max(1, len(rows) // 10))
        eval_rows = rows[split:]
    else:
        split, eval_rows = len(rows), []
    train_ds = Dataset.from_list(rows[:split])
    eval_ds = Dataset.from_list(eval_rows) if eval_rows else None

    def tokenize(batch):
        enc = tokenizer(batch["text"], truncation=True,
                        max_length=CONFIG["seq_len"])
        # Без labels Trainer не получит loss от CausalLM.
        enc["labels"] = [list(ids) for ids in enc["input_ids"]]
        return enc

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.output_dir,
            per_device_train_batch_size=CONFIG["batch"],
            gradient_accumulation_steps=CONFIG["grad_accum"],
            ddp_find_unused_parameters=False if CONFIG["gpus"] > 1 else None,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            warmup_ratio=CONFIG["warmup_pct"] / 100.0,
            logging_steps=20,
            eval_strategy="epoch" if eval_ds is not None else "no",
            save_strategy="epoch",
            report_to=[], seed=CONFIG["seed"]),
        train_dataset=train_ds.map(tokenize, batched=True),
        eval_dataset=(eval_ds.map(tokenize, batched=True)
                      if eval_ds is not None else None),
        # Динамический padding: примеры разной длины дополняются до
        # максимума в батче, labels дополняются -100 (без этого коллатор
        # по умолчанию падает на разной длине последовательностей).
        data_collator=DataCollatorForSeq2Seq(
            tokenizer, padding=True, label_pad_token_id=-100),
    )
    resume_ckpt = None
    if args.resume and os.path.isdir(args.resume):
        if os.path.exists(os.path.join(args.resume, "trainer_state.json")):
            resume_ckpt = args.resume  # полный resume: оптимизатор/шаг/планировщик
    trainer.train(resume_from_checkpoint=resume_ckpt)
    if eval_ds is not None:
        metrics = trainer.evaluate()
        val = metrics.get("eval_loss")
        if val is not None:
            print(f"eval: val_loss={val:.4f}", flush=True)
    else:
        print("eval: пропущен — в датасете одна строка, val-выборки нет",
              flush=True)
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


def distributed_launch_command(cfg: ScriptConfig) -> str:
    """Command to launch the generated script (torchrun when multi-GPU)."""
    if cfg.gpus > 1:
        return f"torchrun --nproc_per_node={cfg.gpus} train_llm.py"
    return "python train_llm.py"


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
