"""Wizard plan assembly + before/after comparison (этап 27).

``build_plan`` folds path/preset/audit/advice/resources into one readable
checklist the user can follow; ``compare_before_after`` diffs eval reports
and generation samples of two logs (baseline vs current).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .data_audit import DataAudit
from .evaluation import build_eval_report
from .gen_preview import compare_samples, parse_samples
from .model_recipes import Advice, ArchPreset, estimate_data_tokens, recommend
from .resource_calc import ResourceEstimate, estimate


@dataclass
class WizardPlan:
    path: str
    recipe_name: str
    preset: ArchPreset
    audit: DataAudit
    advice: Advice
    resources: ResourceEstimate
    data_tokens: int
    steps: list[str] = field(default_factory=list)

    def render(self) -> str:
        rows = [f"🎯 Путь: {self.recipe_name}",
                f"🏗 {self.preset.line()} ({self.preset.note})",
                f"📊 Данные: {self.audit.rows} строк, ~{self.data_tokens} токенов, "
                f"качество {self.audit.score}/100",
                "🧪 Аудит данных:"]
        rows.extend("  " + line for line in self.audit.checklist())
        rows.append("⚙ Рекомендации агента:")
        rows.extend("  " + line for line in self.advice.render().splitlines())
        rows.append("💰 Ресурсы (до старта):")
        rows.extend("  " + line for line in self.resources.render().splitlines())
        rows.append("▶ Шаги:")
        rows.extend(f"  {i}. {s}" for i, s in enumerate(self.steps, 1))
        return "\n".join(rows)


def build_plan(*, path: str, recipe_name: str, preset: ArchPreset,
               audit: DataAudit, max_hourly: float | None = None) -> WizardPlan:
    data_tokens = estimate_data_tokens(audit.chars)
    advice = recommend(path=path, params=preset.params, data_tokens=data_tokens)
    resources = estimate(params=preset.params, data_tokens=data_tokens,
                         epochs=advice.epochs, batch=advice.batch,
                         seq_len=advice.seq_len, path=path, max_hourly=max_hourly)
    steps: list[str] = []
    if audit.pii_hits:
        steps.append("Удалить PII/секреты из данных (аудит нашёл совпадения).")
    if audit.duplicates:
        steps.append(f"Дедуплицировать данные ({audit.duplicates} повторов) на странице «Датасеты».")
    if path == "scratch":
        steps.append("Обучить токенизатор кнопкой ниже и сохранить vocab.")
        steps.append("Создать конфиг архитектуры из пресета в команде обучения.")
    elif path == "lora":
        steps.append("Выбрать базовую instruct-модель в библиотеке моделей.")
        steps.append("Задать LoRA r=16/alpha=32 в команде обучения.")
    else:
        steps.append("Подготовить данные под рецепт (поля prompt/response или label).")
    steps.append("Снять baseline: «Baseline до/после» — лог до обучения.")
    steps.append("Запустить обучение на странице «Обучение»; watchdog следит за плато/NaN.")
    steps.append("Сравнить «до/после» и посмотреть сэмплы генерации (страница «Модель»).")
    steps.append("Экспортировать результат (GGUF/ONNX) со страницы «Модели».")
    return WizardPlan(path=path, recipe_name=recipe_name, preset=preset,
                      audit=audit, advice=advice, resources=resources,
                      data_tokens=data_tokens, steps=steps)


@dataclass
class BeforeAfter:
    before_best: float | None
    after_best: float | None
    delta_pct: float | None
    sample_diff: str = ""
    verdict: str = ""

    def render(self) -> str:
        def fmt(v):
            return "—" if v is None else f"{v:.4f}"
        rows = [f"val_loss: было {fmt(self.before_best)} → стало {fmt(self.after_best)}"]
        if self.delta_pct is not None:
            rows.append(f"Изменение: {self.delta_pct:+.1f}% "
                        f"({'лучше' if self.delta_pct < 0 else 'хуже'})")
        if self.verdict:
            rows.append(self.verdict)
        if self.sample_diff:
            rows.append("")
            rows.append(self.sample_diff)
        return "\n".join(rows)


def compare_before_after(before_log: str, after_log: str) -> BeforeAfter:
    before = build_eval_report(before_log or "")
    after = build_eval_report(after_log or "")
    b, a = before.best_val_loss, after.best_val_loss
    delta = None
    if b not in (None, 0) and a is not None:
        delta = (a - b) / abs(b) * 100.0
    sample_diff = ""
    sb, sa = parse_samples(before_log or ""), parse_samples(after_log or "")
    if sb and sa:
        sample_diff = compare_samples(sb[-1], sa[-1])
    verdict = ""
    if delta is not None:
        verdict = ("✅ Модель улучшилась." if delta < -1 else
                   "⚠ Улучшения нет — проверьте lr/эпохи/данные." if delta > 1
                   else "≈ Без заметных изменений.")
    elif not sb and not sa:
        verdict = "Нет данных eval/сэмплов в логах — добавьте печать eval: и sample."
    return BeforeAfter(b, a, delta, sample_diff, verdict)
