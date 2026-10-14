"""Tests for i18n string packs, hotkey validation and layout presets."""
from __future__ import annotations

import pytest

from alterego_training_hub.hotkeys import (
    DEFAULT_HOTKEYS,
    HotkeyError,
    detect_conflicts,
    resolve_hotkeys,
    save_hotkeys,
    validate_key,
)
from alterego_training_hub.i18n import (
    LANGUAGES,
    current_language,
    missing_keys,
    set_language,
    t,
)
from alterego_training_hub.layouts import (
    NAMED_LAYOUTS,
    LayoutError,
    LayoutState,
    layout_info,
    layout_names,
    load_layout,
    save_layout,
)


def test_i18n_packs_and_fallback():
    assert set(LANGUAGES) == {"ru", "en"}
    assert missing_keys() == []  # packs are in sync
    assert current_language() in LANGUAGES
    set_language("en")
    assert t("nav.editor") == "Code editor"
    assert t("нет такого ключа") == "нет такого ключа"  # key fallback
    assert t("нет такого", default="запасной") == "запасной"
    set_language("xx")  # unknown → ru
    assert current_language() == "ru"
    assert t("nav.editor") == "Редактор кода"
    set_language("ru")


def test_hotkey_defaults_and_validation():
    assert all(validate_key(action.default_key)
               for action in DEFAULT_HOTKEYS.values())
    assert validate_key(" <F5> ") == "<F5>"
    for bad in ("", "Control-j", "<>", "два слова", "<" + "x" * 50 + ">"):
        with pytest.raises(HotkeyError):
            validate_key(bad)


def test_hotkey_resolve_conflicts_and_save():
    resolved = resolve_hotkeys({"page.chat": "<Control-t>",
                                "неизвестно": "<F9>",
                                "app.help": "плохо"})
    assert resolved["page.chat"] == "<Control-t>"
    assert resolved["app.help"] == "<F1>"       # bad key ignored
    assert "неизвестно" not in resolved

    conflicts = detect_conflicts({"a": "<F1>", "b": "<F1>", "c": "<F2>"})
    assert conflicts == [("<F1>", ["a", "b"])]

    changes = save_hotkeys({"page.chat": "<Control-t>"})
    assert changes == {"page.chat": "<Control-t>"}
    with pytest.raises(HotkeyError):
        save_hotkeys({"page.chat": "<Control-p>"})   # conflicts with palette
    with pytest.raises(HotkeyError):
        save_hotkeys({"мусор": "<F2>"})


def test_layouts_presets_and_roundtrip(tmp_path):
    assert set(layout_names()) == set(NAMED_LAYOUTS)
    state = layout_info("analytics")
    assert state.page == "model" and state.bottom_visible is False
    with pytest.raises(LayoutError):
        layout_info("нет такой")

    path = save_layout(tmp_path / "layout.json", state)
    loaded = load_layout(path)
    assert loaded == state

    with pytest.raises(LayoutError):
        load_layout(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(LayoutError):
        load_layout(bad)
    bad.write_text('{"page": "нет такой"}', encoding="utf-8")
    with pytest.raises(LayoutError):
        load_layout(bad)
    with pytest.raises(LayoutError):
        save_layout(tmp_path / "x.json", LayoutState(page="нет"))
