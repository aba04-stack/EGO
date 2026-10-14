"""Stage 22 — localization coverage: every UI string is translatable.

Checks that (1) every key exists in every pack, (2) English values are
complete and Cyrillic-free, (3) every Cyrillic literal in ``ui*.py`` is a
``t()`` message key (docstrings and identity checks excepted), (4) format
patterns parse.
"""
from __future__ import annotations

import ast
import string
from pathlib import Path

from alterego_training_hub import i18n
from alterego_training_hub._l10n_ui import UI_MESSAGES
from alterego_training_hub.i18n import missing_keys, set_language, t

SRC = Path(__file__).resolve().parent.parent / "src" / "alterego_training_hub"


def _has_cyr(text: str) -> bool:
    return any("А" <= c <= "я" or c == "ё" or c == "Ё" for c in text)


def _iter_ui_files():
    return sorted(SRC.glob("ui*.py"))


def test_every_key_exists_in_every_pack():
    assert missing_keys() == []


def test_english_values_are_complete():
    empty = [key for key, value in i18n.STRINGS["en"].items()
             if not str(value).strip()]
    assert empty == []
    cyr = [key for key, value in i18n.STRINGS["en"].items()
           if _has_cyr(value)]
    assert cyr == []


def test_russian_pack_is_identity_for_messages():
    for key in UI_MESSAGES:
        assert i18n.STRINGS["ru"][key] == key


def test_ui_modules_have_no_untranslatable_cyrillic_literals():
    """Every Cyrillic literal must be a t() message key covered by the pack."""
    unpacked_keys = []
    outside = []
    for path in _iter_ui_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip: set[int] = set()
        t_arg_ids: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                skip.add(id(node.value))  # docstring / bare string statement
            if isinstance(node, ast.Compare):
                for sub in ast.walk(node):
                    skip.add(id(sub))     # identity checks: language-free
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name == "t" and node.args and isinstance(node.args[0], ast.Constant):
                    t_arg_ids.add(id(node.args[0]))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and _has_cyr(node.value)):
                continue
            if id(node) in skip:
                continue
            if id(node) in t_arg_ids:
                if node.value not in UI_MESSAGES:
                    unpacked_keys.append(f"{path.name}:{node.lineno}")
                continue
            outside.append(f"{path.name}:{node.lineno}: {node.value[:40]!r}")
    assert unpacked_keys == [], f"t() keys missing from pack: {unpacked_keys[:5]}"
    assert outside == [], f"Cyrillic literals outside t(): {outside[:5]}"


def test_format_patterns_parse():
    formatter = string.Formatter()

    class Anything:
        def __format__(self, spec):
            return spec

    broken = []
    for key in UI_MESSAGES:
        try:
            slots = [name for _, name, _, _ in formatter.parse(key)
                     if name and name.isidentifier()]
            if slots:
                key.format(**{name: Anything() for name in slots})
        except Exception as exc:
            broken.append((key[:40], str(exc)))
    assert broken == []


def test_switching_language_translates_ui_messages():
    previous = i18n.current_language()
    try:
        set_language("en")
        assert t("Сохранить") == "Save"
        assert t("Настройки") == "Settings"
        assert t("Горячие клавиши") == "Keyboard shortcuts"
        set_language("ru")
        assert t("Сохранить") == "Сохранить"
    finally:
        set_language(previous)


def test_generated_pack_is_substantial():
    assert len(UI_MESSAGES) >= 690
    assert all(UI_MESSAGES.values())
