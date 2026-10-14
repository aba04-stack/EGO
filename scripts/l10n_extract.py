#!/usr/bin/env python3
"""Extract UI strings from ``ui*.py`` modules and rewrite them through ``t()``.

Message-as-key style: the Russian text IS the key, so a missing translation
falls back to the original Russian and can never break the UI. Translations
live in ``scripts/l10n_en/*.json`` (merged ``{ru_text: en_text}`` maps) and
are compiled into ``src/alterego_training_hub/_l10n_ui.py``.

Usage:
    python scripts/l10n_extract.py --dump      # list msgids needing EN text
    python scripts/l10n_extract.py --write     # rewrite sources + generate pack
    python scripts/l10n_extract.py --pack      # generate pack only (idempotent)

Skipped (kept as literals): docstrings and anything inside ``compare``
operations (identity checks must stay language-independent).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "alterego_training_hub"
EN_DIR = ROOT / "scripts" / "l10n_en"
OUT = SRC / "_l10n_ui.py"


def _has_cyr(text: str) -> bool:
    return any("А" <= c <= "я" or c == "ё" or c == "Ё" for c in text)


def _char_col(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8"))


def _spans(tree: ast.AST, source: str) -> tuple[dict, list, callable]:
    """Return outermost rewrite spans as ({span: node}, lines, abs_pos)."""
    lines = source.splitlines(keepends=True)
    offsets = []
    total = 0
    for line in lines:
        offsets.append(total)
        total += len(line)

    def abs_pos(lineno: int, byte_col: int) -> int:
        return offsets[lineno - 1] + _char_col(lines[lineno - 1], byte_col)

    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            skip.add(id(node.value))  # bare string statements / docstrings
        if isinstance(node, ast.Compare):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    skip.add(id(sub))
                if isinstance(sub, ast.JoinedStr):
                    skip.add(id(sub))

    def is_doc_or_cmp(n: ast.AST) -> bool:
        return id(n) in skip

    nodes: dict[tuple, ast.AST] = {}
    for node in ast.walk(tree):
        if is_doc_or_cmp(node):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and _has_cyr(node.value):
            span = (abs_pos(node.lineno, node.col_offset),
                    abs_pos(node.end_lineno, node.end_col_offset))
            # In Python 3.11 f-string literal parts share the span of the
            # whole JoinedStr — keep the JoinedStr when spans collide.
            current = nodes.get(span)
            if current is None or isinstance(node, ast.JoinedStr):
                nodes[span] = node
        elif isinstance(node, ast.JoinedStr):
            cooked = "".join(
                part.value if isinstance(part, ast.Constant) else "{}"
                for part in node.values)
            if not _has_cyr(cooked):
                continue
            span = (abs_pos(node.lineno, node.col_offset),
                    abs_pos(node.end_lineno, node.end_col_offset))
            current = nodes.get(span)
            if current is None or isinstance(node, ast.JoinedStr):
                nodes[span] = node
    # Keep only outermost spans (a literal part inside an f-string must not
    # be rewritten on its own).
    outermost: dict[tuple, ast.AST] = {}
    for span, node in nodes.items():
        if any(other != span and other[0] <= span[0] and span[1] <= other[1]
               for other in nodes):
            continue
        outermost[span] = node
    return outermost, lines, abs_pos


def _build_pattern(joined: ast.JoinedStr, source: str, abs_pos) -> tuple[str, str]:
    """Return (format-pattern, args-expression) for a JoinedStr."""
    parts: list[str] = []
    args: list[str] = []
    used: set[str] = set()
    for index, part in enumerate(joined.values):
        if isinstance(part, ast.Constant):
            text = str(part.value).replace("{", "{{").replace("}", "}}")
            parts.append(text)
            continue
        assert isinstance(part, ast.FormattedValue)
        expr = ast.get_source_segment(source, part.value) or ""
        if isinstance(part.value, ast.Name) and part.value.id not in used:
            slot = part.value.id
        else:
            slot = f"v{index}"
        used.add(slot)
        conv = {-1: "", 115: "!s", 114: "!r", 97: "!a"}.get(part.conversion, "")
        spec = ""
        if part.format_spec is not None:
            for spec_part in part.format_spec.values:
                if isinstance(spec_part, ast.Constant):
                    spec += str(spec_part.value)
                else:
                    raise SystemExit(
                        f"Nested format specs unsupported: line {part.lineno}")
            spec = ":" + spec
        parts.append("{" + slot + conv + spec + "}")
        args.append(f"{slot}={expr}")
    pattern = "".join(parts)
    return pattern, ", ".join(args)


def _replacement(node: ast.AST, source: str, abs_pos) -> tuple[str, str]:
    """Return (pattern, replacement-code)."""
    if isinstance(node, ast.Constant):
        text = node.value
        return text, f"t({text!r})"
    pattern, args = _build_pattern(node, source, abs_pos)
    if args:
        return pattern, f"t({pattern!r}).format({args})"
    return pattern, f"t({pattern!r})"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dump"
    EN_DIR.mkdir(exist_ok=True)
    translations: dict[str, str] = {}
    for part in sorted(EN_DIR.glob("*.json")):
        translations.update(json.loads(part.read_text(encoding="utf-8")))

    all_patterns: dict[str, str] = {}  # pattern -> module
    todo: list[str] = []
    rewrites: dict[Path, list[tuple[int, int, str]]] = {}

    for path in sorted(SRC.glob("ui*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        nodes, lines, abs_pos = _spans(tree, source)
        edits = []
        for span, node in nodes.items():
            pattern, repl = _replacement(node, source, abs_pos)
            all_patterns[pattern] = path.name
            edits.append((span[0], span[1], repl))
        edits.sort(reverse=True)
        rewrites[path] = edits

    for pattern in sorted(all_patterns):
        if _has_cyr(translations.get(pattern, "")):
            todo.append(pattern)
        elif pattern not in translations:
            todo.append(pattern)

    if mode == "--dump":
        for pattern in todo:
            print(json.dumps(pattern, ensure_ascii=False))
        print(f"# total={len(all_patterns)} todo={len(todo)}", file=sys.stderr)
        return 0

    # --write: rewrite each ui*.py through t()
    if mode == "--write":
        for path, edits in rewrites.items():
            source = path.read_text(encoding="utf-8")
            for start, end, repl in edits:
                source = source[:start] + repl + source[end:]
            if not re.search(r"^from \.i18n import [^\n]*\bt\b(?!, as)", source,
                             re.M):
                lines = source.splitlines(keepends=True)
                future = next((i for i, line in enumerate(lines)
                               if line.startswith("from __future__")), None)
                if future is not None:
                    at = future + 1
                else:
                    anchor = source.find("\nimport ")
                    anchor2 = source.find("\nfrom ")
                    candidates = [x for x in (anchor, anchor2) if x >= 0]
                    cut = min(candidates) if candidates else source.find("\n")
                    at = None
                    source = (source[:cut + 1] + "from .i18n import t\n"
                              + source[cut + 1:])
                if at is not None:
                    lines.insert(at, "from .i18n import t\n")
                    source = "".join(lines)
            path.write_text(source, encoding="utf-8")

    merged = {pattern: translations.get(pattern, pattern)
              for pattern in sorted(all_patterns)}
    OUT.write_text(
        '"""Generated by scripts/l10n_extract.py — UI message translations."""\n'
        "UI_MESSAGES: dict[str, str] = " + json.dumps(
            merged, ensure_ascii=False, indent=4, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"rewritten: {len(rewrites)} modules, "
          f"messages: {len(merged)}, untranslated: {len(todo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
