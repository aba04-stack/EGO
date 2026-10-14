"""Batch prompt testing: run a suite of prompts against a model, grade answers.

Works with any client that has ``generate(prompt, ...)`` returning an object
with ``output``/``latency_ms``/``error`` (PlaygroundClient-compatible).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


class SuiteError(RuntimeError):
    """Suite input error safe to display."""


@dataclass
class PromptCase:
    prompt: str
    expect_contains: str = ""
    system: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def validate(self) -> None:
        if not self.prompt.strip():
            raise SuiteError("Промпт в наборе не должен быть пустым.")
        if len(self.prompt) > 4000:
            raise SuiteError("Промпт: не более 4000 символов.")


@dataclass
class CaseResult:
    case_id: str
    prompt: str
    output: str
    latency_ms: int
    ok: bool
    error: str = ""
    matched: bool | None = None  # expectation check (None = no expectation)

    @property
    def verdict(self) -> str:
        if self.error:
            return "✗ ошибка"
        if self.matched is False:
            return "✗ не прошёл"
        if self.matched:
            return "✓ ок"
        return "· без критерия"


@dataclass
class SuiteResult:
    model: str
    cases: list[CaseResult] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def passed(self) -> int:
        return sum(1 for case in self.cases
                   if case.ok and case.matched is not False)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def mean_latency_ms(self) -> int:
        latencies = [case.latency_ms for case in self.cases if case.ok]
        return int(sum(latencies) / len(latencies)) if latencies else 0


def default_suite() -> list[PromptCase]:
    """Balanced Russian smoke-suite for any assistant model."""
    return [
        PromptCase(prompt="Объясни одной фразой, что такое градиентный спуск.",
                   expect_contains="градиен"),
        PromptCase(prompt="Посчитай: 17 * 24. Ответь только числом.",
                   expect_contains="408"),
        PromptCase(prompt="Переведи на английский: «Обучение идёт успешно.»",
                   expect_contains="uccess"),
        PromptCase(prompt="Назови столицу Кыргызстана. Одно слово.",
                   expect_contains="Бишкек"),
        PromptCase(prompt="Составь короткий чек-лист проверки модели перед "
                          "релизом (до 5 пунктов)."),
    ]


def run_suite(client, cases: list[PromptCase], *, model: str = "",
              temperature: float = 0.2, max_tokens: int = 400) -> SuiteResult:
    """Run every case sequentially and grade expectations."""
    if not cases:
        raise SuiteError("Набор промптов пуст.")
    if len(cases) > 50:
        raise SuiteError("Не более 50 промптов за прогон.")
    for case in cases:
        case.validate()
    result = SuiteResult(model=model or getattr(client, "model", "?"))
    for case in cases:
        try:
            generated = client.generate(
                case.prompt, system=case.system,
                temperature=temperature, max_tokens=max_tokens)
            error = getattr(generated, "error", "")
            output = getattr(generated, "output", "")
            latency = int(getattr(generated, "latency_ms", 0))
        except Exception as exc:
            error, output, latency = f"{type(exc).__name__}: {exc}", "", 0
        matched: bool | None = None
        if not error and case.expect_contains:
            matched = case.expect_contains.lower() in output.lower()
        result.cases.append(CaseResult(
            case_id=case.id, prompt=case.prompt, output=output,
            latency_ms=latency, ok=not error, error=error, matched=matched))
    return result


def format_suite_report(result: SuiteResult) -> str:
    lines = [f"Модель: {result.model}",
             f"Пройдено: {result.passed}/{result.total}, "
             f"средняя задержка {result.mean_latency_ms} мс", ""]
    for case in result.cases:
        lines.append(f"{case.verdict}  [{case.latency_ms} мс] "
                     f"{case.prompt[:60]}")
        if case.error:
            lines.append(f"    причина: {case.error}")
        elif case.matched is False:
            lines.append(f"    ожидалось: «{case.output[:60]}…»")
    return "\n".join(lines)


def load_suite(path: str | Path) -> list[PromptCase]:
    file = Path(path)
    if not file.is_file():
        raise SuiteError(f"Файл набора не найден: {file}")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SuiteError(f"Некорректный JSON: {exc}") from None
    items = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise SuiteError("Ожидается список cases в JSON.")
    cases = []
    for item in items:
        if not isinstance(item, dict):
            raise SuiteError("Каждый элемент набора — объект с полем prompt.")
        case = PromptCase(
            prompt=str(item.get("prompt") or ""),
            expect_contains=str(item.get("expect_contains") or ""),
            system=str(item.get("system") or ""))
        case.validate()
        cases.append(case)
    return cases


def save_suite(path: str | Path, cases: list[PromptCase]) -> Path:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(
        {"cases": [asdict(case) for case in cases]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return file
