"""Architecture presets, training recipes and hyperparameter advice.

Pure heuristics for the «Своя ЛЛМ» wizard: decoder-transformer parameter
counting, memory estimates and starting-point hyperparameters by path
(LoRA fine-tune / from scratch / task recipe).  No tkinter, no network.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArchPreset:
    id: str
    name: str
    vocab: int
    d_model: int
    layers: int
    heads: int
    seq_len: int
    note: str = ""

    @property
    def params(self) -> int:
        """Approximate decoder-transformer parameter count."""
        d, v, layers = self.d_model, self.vocab, self.layers
        embed = v * d
        per_layer = 12 * d * d  # attn (4d²) + MLP 4·d·2d ≈ 8d²
        return embed + layers * per_layer + 2 * d

    @property
    def params_human(self) -> str:
        p = self.params
        return f"{p/1e9:.2f}B" if p >= 1e9 else f"{p/1e6:.0f}M"

    def line(self) -> str:
        return (f"{self.name}: ~{self.params_human} параметров, "
                f"d={self.d_model}, слоёв={self.layers}, seq={self.seq_len}")


PRESETS: tuple[ArchPreset, ...] = (
    ArchPreset("gpt2-small", "GPT-2 small", 50257, 768, 12, 12, 1024,
               "классика для экспериментов и обучения с нуля на малом корпусе"),
    ArchPreset("gpt2-medium", "GPT-2 medium", 50257, 1024, 24, 16, 1024,
               "заметно сильнее, нужна GPU 16+ ГБ для full FT"),
    ArchPreset("llama-tiny", "Llama-like tiny", 32000, 512, 8, 8, 2048,
               "современная архитектура, быстрый старт с нуля"),
    ArchPreset("llama-small", "Llama-like small", 32000, 1024, 16, 16, 2048,
               "разумный баланс качества и цены"),
    ArchPreset("custom", "Своя конфигурация", 32000, 768, 12, 12, 1024,
               "параметры задаются вручную в конфиге обучения"),
)


def get_preset(preset_id: str) -> ArchPreset:
    for preset in PRESETS:
        if preset.id == preset_id:
            return preset
    return PRESETS[0]


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    path: str  # "lora" | "scratch" | "recipe"
    base_hint: str
    note: str


RECIPES: tuple[Recipe, ...] = (
    Recipe("lora-chat", "Дообучить готовую (LoRA/QLoRA)", "lora",
           "любая instruct-модель 7–8B", "быстро и дёшево, качество базовой сохраняется"),
    Recipe("scratch", "Обучить с нуля", "scratch",
           "свой токенизатор + пресет архитектуры", "полный контроль, нужен большой корпус"),
    Recipe("chatbot", "Рецепт: чат-бот на своих данных", "recipe",
           "LoRA поверх instruct-модели", "диалоги вопрос→ответ из вашего датасета"),
    Recipe("code", "Рецепт: код-ассистент", "recipe",
           "LoRA поверх code-модели", "код + комментарии, тесты как eval"),
    Recipe("classifier", "Рецепт: классификатор", "recipe",
           "дообучение с головой классификации", "метки классов в поле label"),
)


@dataclass(frozen=True)
class Advice:
    lr: float
    batch: int
    warmup_pct: int
    epochs: int
    seq_len: int
    notes: tuple[str, ...] = ()

    def render(self) -> str:
        rows = [f"lr={self.lr:g}, batch={self.batch}, warmup={self.warmup_pct}%, "
                f"эпох={self.epochs}, seq={self.seq_len}"]
        rows.extend(f"• {n}" for n in self.notes)
        return "\n".join(rows)


def recommend(*, path: str, params: int, data_tokens: int) -> Advice:
    """Starting hyperparameters by training path, model size and data volume."""
    notes: list[str] = []
    if path == "lora":
        lr, batch, epochs = 1e-4, 16, 3
        notes.append("LoRA r=16, alpha=32, dropout 0.05 — безопасный старт.")
        if data_tokens < 200_000:
            notes.append("Данных мало: 2 эпохи и ранняя остановка по val_loss.")
            epochs = 2
    elif path == "scratch":
        lr = 3e-4 if params < 300_000_000 else 1e-4
        batch, epochs = 32, 1
        notes.append("С нуля: cosine- decay, warmup обязателен, clip grad=1.0.")
        if data_tokens < 1_000_000:
            notes.append("⚠ Корпус < 1M токенов — модель не выучит язык, "
                         "добавьте данных или выберите LoRA-путь.")
    else:  # recipe
        lr, batch, epochs = 2e-4, 16, 3
        notes.append("Рецепт: начните с 3 эпох, дальше — по кривой val_loss.")
    if params >= 1_000_000_000:
        notes.append("Модель ≥1B: gradient checkpointing и bf16 обязательны.")
    notes.append("Ранняя остановка: patience=2 по val_loss (watchdog отследит плато).")
    return Advice(lr=lr, batch=batch, warmup_pct=5 if path == "scratch" else 3,
                  epochs=epochs, seq_len=1024 if path != "scratch" else 512,
                  notes=tuple(notes))


def estimate_data_tokens(chars: int) -> int:
    """Rough token count from character volume (~3.5 chars/token mixed RU/EN)."""
    return max(0, round(int(chars or 0) / 3.5))
