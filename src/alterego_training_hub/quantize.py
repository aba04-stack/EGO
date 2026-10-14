"""Quantization recipes: size/quality estimates, commands, verification."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

GGUF_MAGIC = b"GGUF"


@dataclass(frozen=True)
class QuantRecipe:
    id: str
    label: str
    bits_per_weight: float     # effective, incl. scales
    quality_delta_pct: float   # expected metric degradation, %
    family: str                # "gguf" | "onnx"


QUANT_RECIPES: dict[str, QuantRecipe] = {
    recipe.id: recipe for recipe in [
        QuantRecipe("q8_0", "Q8_0 — почти без потерь", 8.5, 0.1, "gguf"),
        QuantRecipe("q5_k_m", "Q5_K_M — мягкая компрессия", 5.5, 0.3, "gguf"),
        QuantRecipe("q4_k_m", "Q4_K_M — баланс (рекомендуется)", 4.9, 0.8, "gguf"),
        QuantRecipe("q4_0", "Q4_0 — максимум экономии", 4.5, 2.0, "gguf"),
        QuantRecipe("q3_k_m", "Q3_K_M — агрессивная", 3.9, 4.0, "gguf"),
        QuantRecipe("int8", "INT8 (ONNX dynamic)", 8.0, 1.5, "onnx"),
    ]
}


class QuantizeError(RuntimeError):
    """Quantization input error safe to display."""


def recipe_info(recipe_id: str) -> QuantRecipe:
    recipe = QUANT_RECIPES.get(str(recipe_id or "").lower())
    if recipe is None:
        raise QuantizeError(f"Рецепт квантизации: один из {sorted(QUANT_RECIPES)}.")
    return recipe


def estimate_size(model_bytes: int, recipe_id: str) -> int:
    """Projected artifact size in bytes (weights at the recipe's bpw)."""
    recipe = recipe_info(recipe_id)
    base = int(model_bytes)
    if base <= 0:
        raise QuantizeError("Размер исходной модели должен быть больше нуля.")
    return int(base * recipe.bits_per_weight / 16.0)  # fp16 baseline


def size_reduction(model_bytes: int, recipe_id: str) -> float:
    recipe = recipe_info(recipe_id)
    return 16.0 / recipe.bits_per_weight


def build_quantize_command(source: str, destination: str,
                           recipe_id: str, *, quantize_tool: str = "llama-quantize") \
        -> list[str]:
    recipe = recipe_info(recipe_id)
    if not str(source).strip() or not str(destination).strip():
        raise QuantizeError("Укажите исходный и выходной файлы.")
    if recipe.family == "onnx":
        # Dynamic ONNX quantization via onnxruntime tooling.
        return ["python", "-m", "onnxruntime.quantization.quantize",
                "--input", source, "--output", destination, "--mode", "dynamic"]
    return [quantize_tool, recipe.id.upper(), source, destination]


def verify_quantized(source: str, destination: str, recipe_id: str) -> list[str]:
    """Sanity checks: magic bytes, plausible size ratio vs. recipe."""
    recipe = recipe_info(recipe_id)
    checks: list[str] = []
    src, dst = Path(source), Path(destination)
    if not dst.is_file():
        return ["✗ квантизованная модель не создана"]
    dst_size = dst.stat().st_size
    checks.append(f"✓ файл: {dst.name} ({dst_size / 1_048_576:.1f} MB)")
    if recipe.family == "gguf":
        with dst.open("rb") as handle:
            magic = handle.read(4)
        if magic != GGUF_MAGIC:
            checks.append(f"✗ неверный формат (нет GGUF-магии): {magic!r}")
            return checks
        checks.append("✓ магия GGUF подтверждена")
    if src.is_file() and src.stat().st_size > 0:
        ratio = src.stat().st_size / max(1, dst_size)
        expected = 16.0 / recipe.bits_per_weight
        if ratio < expected * 0.5:
            checks.append(f"✗ размер почти не уменьшился (×{ratio:.2f}, "
                          f"ожидалось ~×{expected:.1f})")
            return checks
        checks.append(f"✓ сжатие ×{ratio:.1f} (рецепт: ×{expected:.1f})")
    if dst_size < 1024:
        checks.append("✗ файл подозрительно мал")
        return checks
    checks.append("✓ проверка пройдена")
    return checks


@dataclass
class QuantResult:
    ok: bool
    recipe: str
    command: list[str] = field(default_factory=list)
    output_path: str = ""
    checks: list[str] = field(default_factory=list)
    log_tail: str = ""
    error: str = ""
    duration_s: float = 0.0


def run_quantize(source: str, destination: str, recipe_id: str, *,
                 quantize_tool: str = "llama-quantize", timeout_seconds: float = 600.0,
                 runner=None) -> QuantResult:
    started = time.monotonic()
    try:
        command = build_quantize_command(source, destination, recipe_id,
                                         quantize_tool=quantize_tool)
    except QuantizeError as exc:
        return QuantResult(ok=False, recipe=recipe_id, error=str(exc))
    log_tail = ""
    try:
        if runner is not None:
            completed = runner(command)
            returncode = getattr(completed, "returncode", 0)
            log_tail = str(getattr(completed, "stdout", "") or "")[-2000:]
        else:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=max(30.0, float(timeout_seconds)))
            returncode = completed.returncode
            log_tail = ((completed.stdout or "") + "\n" + (completed.stderr or ""))[-2000:]
    except FileNotFoundError:
        return QuantResult(ok=False, recipe=recipe_id, command=command,
                           error=f"Инструмент не найден: {command[0]}. "
                                 "Для GGUF нужен llama.cpp (llama-quantize).")
    except subprocess.TimeoutExpired:
        return QuantResult(ok=False, recipe=recipe_id, command=command,
                           error="Квантизация превысила таймаут.")
    if returncode != 0:
        return QuantResult(ok=False, recipe=recipe_id, command=command,
                           log_tail=log_tail,
                           error=f"Квантизация завершилась с кодом {returncode}.")
    checks = verify_quantized(source, destination, recipe_id)
    ok = not any(line.startswith("✗") for line in checks)
    return QuantResult(ok=ok, recipe=recipe_id, command=command,
                       output_path=destination, checks=checks, log_tail=log_tail,
                       duration_s=time.monotonic() - started,
                       error="" if ok else "Проверка квантизации не пройдена.")


def format_quant_report(recipe_id: str, model_bytes: int) -> str:
    recipe = recipe_info(recipe_id)
    projected = estimate_size(model_bytes, recipe_id)
    return (f"{recipe.label}: ~{projected / 1_048_576:.0f} MB "
            f"(×{size_reduction(model_bytes, recipe_id):.1f} меньше), "
            f"ожидаемая потеря качества ~{recipe.quality_delta_pct:g}%")
