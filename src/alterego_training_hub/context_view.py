"""Context view: what the model actually sees — prompt, tokens, cost.

Pure heuristics (no network, no tiktoken): token estimate is ~4 characters
per token, cost estimate uses a small pricing table by model family.  The
point is transparency, not billing accuracy.

Pure logic — no tkinter, no network.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# Rough USD per 1M tokens (input, output) by model family.  Heuristic only.
_PRICE_TABLE: tuple[tuple[str, float, float], ...] = (
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.00),
    ("gpt-4.1", 2.00, 8.00),
    ("gpt-4", 10.00, 30.00),
    ("gpt-3.5", 0.50, 1.50),
    ("o3", 2.00, 8.00),
    ("o1", 15.00, 60.00),
    ("deepseek-reasoner", 0.55, 2.19),
    ("deepseek-chat", 0.27, 1.10),
    ("deepseek", 0.27, 1.10),
    ("claude-3-5-haiku", 0.80, 4.00),
    ("claude-3-5", 3.00, 15.00),
    ("claude-3", 3.00, 15.00),
    ("claude", 3.00, 15.00),
    ("gemini-1.5-flash", 0.075, 0.30),
    ("gemini", 1.25, 5.00),
    ("llama", 0.20, 0.20),
    ("qwen", 0.20, 0.20),
)
_DEFAULT_PRICE = (1.00, 3.00)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate: ~4 chars per token, at least 1 for non-empty."""
    length = len(text or "")
    if length == 0:
        return 0
    return max(1, round(length / 4))


def price_for_model(model: str) -> tuple[float, float]:
    """(usd_per_1m_input, usd_per_1m_output) for a model name, heuristic."""
    name = (model or "").lower()
    for needle, pin, pout in _PRICE_TABLE:
        if needle in name:
            return pin, pout
    return _DEFAULT_PRICE


def estimate_cost(prompt_tokens: int, completion_tokens: int,
                  model: str) -> float:
    """Estimated USD cost of one request.  Heuristic — for orientation."""
    pin, pout = price_for_model(model)
    return (max(0, int(prompt_tokens)) * pin
            + max(0, int(completion_tokens)) * pout) / 1_000_000.0


def format_usage(usage: Mapping[str, Any] | None, *, model: str = "") -> str:
    """One-line summary of a reply usage dict (OpenAI-style keys)."""
    if not usage:
        return "токены: нет данных"
    prompt = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    completion = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    total = int(usage.get("total_tokens", prompt + completion) or 0)
    cost = estimate_cost(prompt, completion, model or str(usage.get("model", "")))
    return (f"токены: {prompt} → {completion} (всего {total}"
            + (f", ≈${cost:.4f}" if model or usage.get("model") else "") + ")")


@dataclass
class ContextView:
    """Transparent breakdown of the request context."""

    model: str
    system_prompt: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    system_tokens: int = 0
    history_tokens: int = 0
    total_tokens: int = 0
    est_cost: float = 0.0
    last_usage: dict[str, Any] = field(default_factory=dict)

    def render(self, *, max_system: int = 600) -> str:
        rows = [
            f"Модель: {self.model or '—'}",
            f"Системный промпт: {self.system_tokens} ток. "
            f"(≈{len(self.system_prompt)} символов)",
            f"История: {len(self.messages)} сообщений, "
            f"{self.history_tokens} ток.",
            f"Итого контекст: ≈{self.total_tokens} ток., "
            f"≈${self.est_cost:.4f} за запрос",
        ]
        if self.last_usage:
            rows.append("Последний реальный запрос: "
                        + format_usage(self.last_usage, model=self.model))
        rows.append("")
        rows.append("--- Системный промпт (фрагмент) ---")
        rows.append((self.system_prompt or "—")[:max_system])
        return "\n".join(rows)


def build_context_view(*, system_prompt: str,
                       messages: Iterable[Mapping[str, Any]],
                       model: str = "",
                       last_usage: Mapping[str, Any] | None = None,
                       completion_tokens: int = 300) -> ContextView:
    """Build a :class:`ContextView` from the prompt and API-style history."""
    history = [dict(m) for m in messages]
    history_tokens = sum(
        estimate_tokens(str(m.get("content") or "")) + 4 for m in history)
    system_tokens = estimate_tokens(system_prompt or "")
    total = system_tokens + history_tokens
    cost = estimate_cost(total, completion_tokens, model)
    return ContextView(
        model=str(model),
        system_prompt=str(system_prompt or ""),
        messages=history,
        system_tokens=system_tokens,
        history_tokens=history_tokens,
        total_tokens=total,
        est_cost=cost,
        last_usage=dict(last_usage or {}),
    )
