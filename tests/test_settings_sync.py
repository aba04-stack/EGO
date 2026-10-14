"""Tests for settings sync bundles (export/import, folder push/pull)."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.config import AppSettings
from alterego_training_hub.settings_sync import (
    SettingsSyncError,
    apply_bundle,
    bundle,
    export_settings,
    import_bundle,
    pull,
    push,
)


def test_bundle_round_trip(tmp_path):
    settings = AppSettings.load()
    settings.ui_language = "en"
    settings.hotkeys = {"palette.files": "<Control-p>"}
    file = export_settings(tmp_path / "nested" / "settings.json", settings)
    assert file.exists()  # parent dirs created

    raw = import_bundle(file)
    fresh = AppSettings.load()
    changed = apply_bundle(fresh, raw)
    assert "ui_language" in changed
    assert fresh.ui_language == "en"
    assert fresh.hotkeys == {"palette.files": "<Control-p>"}
    # idempotent second apply
    assert apply_bundle(fresh, raw) == []


def test_apply_bundle_skips_unknown_and_mismatched_types():
    settings = AppSettings.load()
    settings.ui_language = "ru"
    changed = apply_bundle(settings, {"fields": {
        "ui_language": 5,            # type mismatch: skipped
        "hacker_field": "x",         # unknown: skipped
        "ui_theme": "dark",          # valid
    }})
    assert changed == ["ui_theme"]
    assert settings.ui_theme == "dark"
    assert settings.ui_language == "ru"


def test_import_bundle_validates(tmp_path):
    with pytest.raises(SettingsSyncError):
        import_bundle(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsSyncError):
        import_bundle(bad)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"app": "other", "fields": {}}),
                     encoding="utf-8")
    with pytest.raises(SettingsSyncError):
        import_bundle(wrong)


def test_push_pull_last_write_wins(tmp_path):
    folder = tmp_path / "sync"
    a = AppSettings.load()
    a.ui_language = "en"
    push(a, folder)

    b = AppSettings.load()
    applied, changed = pull(b, folder)
    assert applied and "ui_language" in changed and b.ui_language == "en"
    # second pull: nothing newer
    applied, changed = pull(b, folder)
    assert not applied and changed == []

    # newer push from A wins again
    a.ui_theme = "dark"
    push(a, folder)
    applied, changed = pull(b, folder)
    assert applied and "ui_theme" in changed and b.ui_theme == "dark"


def test_bundle_never_contains_secrets(tmp_path):
    settings = AppSettings.load()
    names = set(bundle(settings)["fields"])
    assert "api_key" not in " ".join(names)
    assert all(not name.endswith("_key") for name in names)
