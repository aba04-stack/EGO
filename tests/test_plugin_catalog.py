"""Tests for the plugin catalog: install, validation, uninstall."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.plugin_catalog import (
    CatalogEntry,
    CatalogError,
    install_entry,
    load_catalog,
    save_catalog,
    uninstall,
)

PLUGIN_SOURCE = '''
PLUGIN = {"id": "mini", "name": "Mini", "version": "2.0",
          "tools": {"ping": {
              "schema": {"type": "function", "function": {
                  "name": "ping", "description": "ping",
                  "parameters": {"type": "object", "properties": {}}}},
              "handler": lambda args: {"ok": True}}}}
'''


def test_install_from_file_source(tmp_path):
    source = tmp_path / "vendor" / "mini_plugin.py"
    source.parent.mkdir(parents=True)
    source.write_text(PLUGIN_SOURCE, encoding="utf-8")
    entry = CatalogEntry(id="mini", name="Mini", version="2.0",
                         source=f"file:{source}")
    target = install_entry(entry, tmp_path / "plugins")
    assert target.name == "mini.py"
    assert target.read_text(encoding="utf-8") == PLUGIN_SOURCE

    from alterego_training_hub.plugins import PluginManager
    plugins = PluginManager(tmp_path / "plugins").load_all()
    assert [p.name for p in plugins] == ["Mini"]
    assert plugins[0].version == "2.0"


def test_install_relative_file_source(tmp_path):
    vendor = tmp_path / "examples"
    vendor.mkdir()
    (vendor / "rel.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    entry = CatalogEntry(id="rel", name="Rel", source="file:examples/rel.py")
    target = install_entry(entry, tmp_path / "plugins", base_dir=tmp_path)
    assert target.exists()


def test_install_checks_sha256(tmp_path):
    import hashlib

    source = tmp_path / "mini.py"
    source.write_text(PLUGIN_SOURCE, encoding="utf-8")
    good = hashlib.sha256(PLUGIN_SOURCE.encode("utf-8")).hexdigest()
    entry = CatalogEntry(id="mini", name="Mini", source=f"file:{source}",
                         sha256=good)
    assert install_entry(entry, tmp_path / "plugins").exists()

    bad = CatalogEntry(id="mini2", name="Mini", source=f"file:{source}",
                       sha256="0" * 64)
    with pytest.raises(CatalogError):
        install_entry(bad, tmp_path / "plugins")


def test_install_rejects_junk_files(tmp_path):
    source = tmp_path / "junk.py"
    source.write_text("print('hello')\n", encoding="utf-8")
    entry = CatalogEntry(id="junk", name="Junk", source=f"file:{source}")
    with pytest.raises(CatalogError):
        install_entry(entry, tmp_path / "plugins")


def test_load_catalog_validation(tmp_path):
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(bad)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"entries": []}), encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(wrong)
    no_source = tmp_path / "nosource.json"
    no_source.write_text(json.dumps([{"id": "x", "name": "X"}]),
                         encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(no_source)
    bad_scheme = tmp_path / "scheme.json"
    bad_scheme.write_text(
        json.dumps([{"id": "x", "name": "X", "source": "ftp://y"}]),
        encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(bad_scheme)


def test_save_catalog_round_trip(tmp_path):
    entries = [CatalogEntry(id="a", name="A", version="1", source="file:a.py"),
               CatalogEntry(id="b", name="B", source="https://example.com/b.py")]
    file = save_catalog(tmp_path / "catalogs" / "mine.json", entries)
    loaded = load_catalog(file)
    assert [entry.id for entry in loaded] == ["a", "b"]
    assert loaded[1].source.startswith("https://")


def test_uninstall_removes_plugin_file(tmp_path):
    source = tmp_path / "mini.py"
    source.write_text(PLUGIN_SOURCE, encoding="utf-8")
    entry = CatalogEntry(id="mini", name="Mini", source=f"file:{source}")
    target = install_entry(entry, tmp_path / "plugins")
    assert uninstall("mini", tmp_path / "plugins") is True
    assert not target.exists()
    assert uninstall("mini", tmp_path / "plugins") is False
