"""Resource calculator: parameters → VRAM → hours → dollars (before start!).

Heuristic catalog of common cloud GPUs with typical RunPod-style hourly
prices; deliberately labelled estimates, not quotes.  Pure logic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GpuOption:
    name: str
    vram_gb: int
    usd_per_hour: float
    tokens_per_sec_7b: float  # rough training throughput anchor at ~7B full FT

    def fits(self, need_gb: float) -> bool:
        return self.vram_gb >= need_gb


GPU_CATALOG: tuple[GpuOption, ...] = (
    GpuOption("RTX 3090", 24, 0.30, 9000),
    GpuOption("RTX 4090", 24, 0.45, 14000),
    GpuOption("A40", 48, 0.40, 11000),
    GpuOption("RTX A6000", 48, 0.55, 12000),
    GpuOption("A100 40GB", 40, 1.10, 22000),
    GpuOption("A100 80GB", 80, 1.60, 24000),
    GpuOption("H100 80GB", 80, 2.40, 45000),
)


def memory_need_gb(params: int, *, path: str = "lora", seq_len: int = 1024,
                   batch: int = 16) -> float:
    """Estimated training VRAM in GB.

    full: weights bf16 (2B) + grads bf16 (2B) + Adam fp32 states+m+v+master (~12B)
    lora: frozen bf16 weights + small adapter/optimizer + activations.
    Activations approximated with gradient checkpointing.
    """
    p = max(0, int(params))
    if path == "lora":
        weights = p * 2 / 1e9
        adapter = 0.3 + p * 0.02 / 1e9
        act = max(1.0, seq_len * batch / 4096)
        return round(weights + adapter + act, 1)
    weights_grads_adam = p * 16 / 1e9
    act = max(2.0, seq_len * batch / 2048)
    return round(weights_grads_adam + act, 1)


def throughput_tps(gpu: GpuOption, params: int, *, path: str = "lora",
                   seq_len: int = 1024, batch: int = 16) -> float:
    """Tokens/sec from the 7B anchor.

    Масштаб по размеру модели — степенной (показатель 0.9, не линейный:
    маленькие модели упираются в накладные расходы, не в FLOPs), длинные
    последовательности замедляют токен (внимание), малый batch недогружает
    GPU. Это по-прежнему эвристика с разбросом ±~2x — render() так и пишет.
    """
    scale = (7e9 / max(1, int(params))) ** 0.9
    tps = gpu.tokens_per_sec_7b * min(4.0, max(0.12, scale))
    if seq_len > 1024:
        tps /= 1.0 + (seq_len - 1024) / 8192.0
    if batch < 16:
        tps *= 0.6 + 0.4 * (max(1, batch) / 16.0)
    return tps * (1.6 if path == "lora" else 1.0)


@dataclass
class ResourceEstimate:
    params: int
    need_gb: float
    steps: int
    hours: float
    gpu: GpuOption | None
    cost_usd: float

    def render(self) -> str:
        rows = [f"Параметры: {self.params/1e6:.0f}M · нужно VRAM: ~{self.need_gb:.1f} ГБ",
                f"Шагов: ~{self.steps}"]
        if self.gpu is None:
            rows.append("⚠ Ни одна GPU из каталога не подходит — уменьшите модель/batch/seq "
                        "или используйте QLoRA/мульти-GPU.")
        else:
            rows.append(f"Рекомендация: {self.gpu.name} ({self.gpu.vram_gb} ГБ, "
                        f"${self.gpu.usd_per_hour:.2f}/ч)")
            rows.append(f"Время: ~{self.hours:.1f} ч · стоимость: ~${self.cost_usd:.2f} "
                        f"(оценка, не котировка)")
            rows.append("⚠ Эвристика по каталожным ценам и якорной скорости 7B: "
                        "реальное время легко отличается в 1.5–2 раза в обе "
                        "стороны (архитектура, оптимизатор, данные).")
        return "\n".join(rows)


def estimate(*, params: int, data_tokens: int, epochs: int = 3, batch: int = 16,
             seq_len: int = 1024, path: str = "lora",
             max_hourly: float | None = None) -> ResourceEstimate:
    need = memory_need_gb(params, path=path, seq_len=seq_len, batch=batch)
    tokens_total = max(0, int(data_tokens)) * max(1, int(epochs))
    steps = max(1, tokens_total // max(1, batch * seq_len)) if tokens_total else 0
    fitting = [g for g in GPU_CATALOG if g.fits(need)
               and (max_hourly is None or g.usd_per_hour <= max_hourly)]
    if not fitting:
        return ResourceEstimate(params, need, steps, 0.0, None, 0.0)
    # cheapest fitting GPU that is not absurdly slow: min cost = price / tps
    gpu = min(fitting, key=lambda g: g.usd_per_hour / max(
        1.0, throughput_tps(g, params, path=path, seq_len=seq_len, batch=batch)))
    tps = throughput_tps(gpu, params, path=path, seq_len=seq_len, batch=batch)
    hours = (tokens_total / tps / 3600.0) if tokens_total else 0.0
    return ResourceEstimate(params, need, steps, round(hours, 2), gpu,
                            round(hours * gpu.usd_per_hour, 2))
