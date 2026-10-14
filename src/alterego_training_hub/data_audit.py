"""Dataset audit for the wizard: duplicates, empties, PII risks, language mix.

Operates on row dicts (datasets.read_rows) or plain text lines.  Pure logic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\d\s\-()]{9,}\d)")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SECRET = re.compile(r"(?i)(sk-[a-z0-9]{10,}|api[_-]?key\s*[:=]|password\s*[:=])")


def _text_of(row) -> str:
    if isinstance(row, str):
        return row
    if isinstance(row, dict):
        messages = row.get("messages")
        if isinstance(messages, list):
            parts = [str(m.get("content", "")) for m in messages
                     if isinstance(m, dict) and m.get("content")]
            if parts:
                return "\n".join(parts)
        for key in ("text", "prompt", "instruction", "question", "input", "content"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                answer = row.get("output") or row.get("completion") \
                    or row.get("response") or ""
                return value + (f"\n{answer}" if answer else "")
        return " ".join(str(v) for v in row.values() if isinstance(v, str))
    return str(row or "")


@dataclass
class DataAudit:
    rows: int = 0
    chars: int = 0
    duplicates: int = 0
    empty: int = 0
    too_short: int = 0
    pii_hits: int = 0
    cyrillic_share: float = 0.0
    avg_len: float = 0.0
    issues: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        """0..100 quality score (heuristic)."""
        if self.rows == 0:
            return 0
        score = 100
        score -= min(30, round(30 * self.duplicates / max(1, self.rows)))
        score -= min(20, round(20 * (self.empty + self.too_short) / max(1, self.rows)))
        score -= 25 if self.pii_hits else 0
        if self.rows < 100:
            score -= 15
        return max(0, score)

    def checklist(self) -> list[str]:
        items = [
            f"{'✓' if self.rows >= 100 else '⚠'} Строк: {self.rows} (для LoRA желательно ≥100)",
            f"{'✓' if self.duplicates == 0 else '⚠'} Дубликаты: {self.duplicates}",
            f"{'✓' if self.empty == 0 else '⚠'} Пустые: {self.empty}, слишком короткие: {self.too_short}",
            f"{'✓' if self.pii_hits == 0 else '✗'} PII/секреты (email, телефоны, ключи): {self.pii_hits}",
            f"• Язык: кириллица {self.cyrillic_share:.0%}, средняя длина {self.avg_len:.0f} симв.",
            f"• Оценка качества: {self.score}/100",
        ]
        items.extend(f"⚠ {issue}" for issue in self.issues)
        return items

    def render(self) -> str:
        return "\n".join(self.checklist())


def audit_rows(rows, *, min_len: int = 10) -> DataAudit:
    items = list(rows or [])
    audit = DataAudit(rows=len(items))
    seen: set[str] = set()
    cyr = lat = 0
    for row in items:
        text = _text_of(row).strip()
        audit.chars += len(text)
        if not text:
            audit.empty += 1
            continue
        if len(text) < min_len:
            audit.too_short += 1
        key = " ".join(text.lower().split())
        if key in seen:
            audit.duplicates += 1
        seen.add(key)
        if _EMAIL.search(text) or _PHONE.search(text) or _CARD.search(text) or _SECRET.search(text):
            audit.pii_hits += 1
        cyr += sum(1 for ch in text if "а" <= ch.lower() <= "я")
        lat += sum(1 for ch in text if "a" <= ch.lower() <= "z")
    total_alpha = cyr + lat
    audit.cyrillic_share = (cyr / total_alpha) if total_alpha else 0.0
    audit.avg_len = (audit.chars / audit.rows) if audit.rows else 0.0
    if audit.rows == 0:
        audit.issues.append("Датасет пуст — обучение не стартует.")
    if audit.pii_hits:
        audit.issues.append("Найдены PII/секреты — удалите до загрузки в облако.")
    if audit.duplicates > max(5, audit.rows // 5):
        audit.issues.append("Много дубликатов — модель зазубрит повторы (дедупликация на странице «Датасеты»).")
    return audit
