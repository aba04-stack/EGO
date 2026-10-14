"""SFT data quality (stage 43): format validation, near-dup, decontamination.

* :func:`validate_sft` — checks instruction/chat formats (Alpaca
  ``instruction/output``, ``prompt/completion``, OpenAI ``messages``):
  role order, missing assistant reply, empty contents.
* :func:`near_duplicate_pairs` — word-shingle Jaccard near-duplicates
  (exact-dup audit in :mod:`data_audit` misses paraphrases).
* :func:`decontaminate` — train rows that nearly duplicate any eval
  row (benchmark leakage) so eval numbers stay honest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .data_audit import _text_of

_TOKEN = re.compile(r"[a-zа-я0-9]+")
VALID_ROLES = {"system", "user", "assistant", "tool"}


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(str(text).lower()))


def shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = _TOKEN.findall(str(text).lower())
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------- SFT format
@dataclass
class SftReport:
    rows: int = 0
    formats: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    problem_rows: int = 0

    @property
    def ok(self) -> bool:
        return self.rows > 0 and self.problem_rows == 0

    def render(self) -> str:
        lines = [f"SFT-валидация: строк {self.rows}, "
                 f"с проблемами {self.problem_rows}"]
        for name, count in sorted(self.formats.items()):
            lines.append(f"  · {name}: {count}")
        lines.extend(f"  ⚠ {p}" for p in self.problems[:10])
        if self.ok:
            lines.append("  ✓ Формат чистый — можно обучать.")
        return "\n".join(lines)


def _row_format(row) -> str:
    if isinstance(row, dict):
        if isinstance(row.get("messages"), list):
            return "messages"
        if "instruction" in row:
            return "alpaca"
        if "prompt" in row and ("completion" in row or "response" in row):
            return "prompt/completion"
        if "text" in row:
            return "text"
    return "unknown"


def _check_row(row, index: int) -> list[str]:
    prefix = f"строка {index + 1}: "
    if not isinstance(row, dict):
        return [prefix + "не объект JSON"]
    fmt = _row_format(row)
    if fmt == "messages":
        messages = row["messages"]
        if not messages:
            return [prefix + "пустой список messages"]
        problems = []
        roles = []
        for msg in messages:
            if not isinstance(msg, dict):
                problems.append(prefix + "сообщение не объект")
                continue
            role = str(msg.get("role", ""))
            roles.append(role)
            if role not in VALID_ROLES:
                problems.append(prefix + f"неизвестная роль {role!r}")
            if not str(msg.get("content", "")).strip():
                problems.append(prefix + f"пустой content у {role or '?'}")
        if "user" not in roles:
            problems.append(prefix + "нет user-сообщения")
        if not roles or roles[-1] != "assistant":
            problems.append(prefix + "диалог не заканчивается assistant")
        return problems
    if fmt == "alpaca":
        problems = []
        if not str(row.get("instruction", "")).strip():
            problems.append(prefix + "пустой instruction")
        if not str(row.get("output", "")).strip():
            problems.append(prefix + "пустой output (ответ ассистента)")
        return problems
    if fmt == "prompt/completion":
        problems = []
        if not str(row.get("prompt", "")).strip():
            problems.append(prefix + "пустой prompt")
        answer = row.get("completion", row.get("response", ""))
        if not str(answer).strip():
            problems.append(prefix + "пустой completion (ответ ассистента)")
        return problems
    if fmt == "text":
        if not str(row.get("text", "")).strip():
            return [prefix + "пустой text"]
        return []
    return [prefix + "неизвестный формат (нет messages/instruction/prompt/text)"]


def validate_sft(rows) -> SftReport:
    items = list(rows or [])
    report = SftReport(rows=len(items))
    for index, row in enumerate(items):
        fmt = _row_format(row)
        report.formats[fmt] = report.formats.get(fmt, 0) + 1
        problems = _check_row(row, index)
        if problems:
            report.problem_rows += 1
            report.problems.extend(problems)
    return report


# --------------------------------------------------------------- near-dup
def near_duplicate_pairs(rows, threshold: float = 0.85,
                         limit: int = 5000) -> list[tuple[int, int, float]]:
    """Pairs (i, j, similarity) with shingle Jaccard >= threshold.

    Candidate pairs come from a shingle inverted index, so this stays
    usable on a few thousand rows without an O(n²) blow-up.
    """
    items = list(rows or [])[:limit]
    shingle_sets = [shingles(_text_of(row)) for row in items]
    index: dict[tuple[str, ...], list[int]] = {}
    for i, shingle_set in enumerate(shingle_sets):
        for shingle in shingle_set:
            index.setdefault(shingle, []).append(i)
    candidates: set[tuple[int, int]] = set()
    for holders in index.values():
        for a in range(len(holders)):
            for b in range(a + 1, len(holders)):
                candidates.add((holders[a], holders[b]))
    pairs = []
    for i, j in sorted(candidates):
        score = jaccard(shingle_sets[i], shingle_sets[j])
        if score >= threshold:
            pairs.append((i, j, round(score, 3)))
    return pairs


def dedupe_near(rows, threshold: float = 0.85) -> tuple[list, int]:
    """Drop later rows of every near-dup pair; returns (kept, removed)."""
    items = list(rows or [])
    removed: set[int] = set()
    for i, j, _score in near_duplicate_pairs(items, threshold):
        if i not in removed:
            removed.add(j)
    kept = [row for k, row in enumerate(items) if k not in removed]
    return kept, len(removed)


# --------------------------------------------------------------- decontamination
@dataclass
class DecontaminationResult:
    contaminated: list[int] = field(default_factory=list)
    cleaned: list = field(default_factory=list)

    def render(self) -> str:
        return (f"Деконтаминация: заражено строк train: "
                f"{len(self.contaminated)}; осталось {len(self.cleaned)}")


def decontaminate(train_rows, eval_rows, threshold: float = 0.8,
                  limit: int = 5000) -> DecontaminationResult:
    """Train rows nearly duplicating any eval row are leakage — remove."""
    train = list(train_rows or [])[:limit]
    eval_shingles = [shingles(_text_of(row)) for row in (eval_rows or [])]
    eval_index: dict[tuple[str, ...], list[int]] = {}
    for k, shingle_set in enumerate(eval_shingles):
        for shingle in shingle_set:
            eval_index.setdefault(shingle, []).append(k)
    contaminated: list[int] = []
    for i, row in enumerate(train):
        shingle_set = shingles(_text_of(row))
        candidates = set()
        for shingle in shingle_set:
            candidates.update(eval_index.get(shingle, []))
        if any(jaccard(shingle_set, eval_shingles[k]) >= threshold
               for k in candidates):
            contaminated.append(i)
    bad = set(contaminated)
    cleaned = [row for k, row in enumerate(train) if k not in bad]
    return DecontaminationResult(contaminated=contaminated, cleaned=cleaned)
