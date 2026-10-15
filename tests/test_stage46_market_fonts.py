"""Этап 46: git-маркет плагинов и подбор шрифтов."""
import json
from pathlib import Path
from types import SimpleNamespace

from alterego_training_hub.plugin_catalog import CatalogError
from alterego_training_hub.plugin_market import load_market, parse_market
from alterego_training_hub.theme import detect_fonts, set_fonts

PLUGIN = '"""demo"""\nPLUGIN = {"name": "Demo", "tools": []}\n'


def test_parse_folder_market(tmp_path):
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "plugin.py").write_text(PLUGIN, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps(
        {"name": "Demo", "version": "1.2"}), encoding="utf-8")
    entries = parse_market(tmp_path)
    assert len(entries) == 1 and entries[0].name == "Demo"


def test_parse_catalog_market(tmp_path):
    (tmp_path / "p.py").write_text(PLUGIN, encoding="utf-8")
    (tmp_path / "catalog.json").write_text(json.dumps(
        [{"id": "x", "source": "p.py"}]), encoding="utf-8")
    entries = parse_market(tmp_path)
    assert entries[0].source.endswith("p.py")
    (tmp_path / "catalog.json").write_text(json.dumps(
        [{"id": "y", "source": "../evil.py"}]), encoding="utf-8")
    try:
        parse_market(tmp_path)
    except CatalogError:
        pass
    else:
        raise AssertionError("path escape must fail")


def test_sync_repo_clones_then_installs(tmp_path):
    repo = tmp_path / "repo"
    (repo / "demo").mkdir(parents=True)
    (repo / "demo" / "plugin.py").write_text(PLUGIN, encoding="utf-8")
    calls = []

    def fake_runner(argv, cwd=None):
        calls.append(argv[1])
        dest = Path(argv[-1]) if argv[1] == "clone" else cwd
        import shutil
        if argv[1] == "clone":
            shutil.copytree(repo, dest, dirs_exist_ok=True)
            (dest / ".git").mkdir(exist_ok=True)
        return SimpleNamespace(returncode=0, stderr="")

    entries = load_market("https://example/market.git",
                          base=tmp_path / "cache", runner=fake_runner)
    assert calls == ["clone"] and entries[0].id == "demo"
    plugins_dir = tmp_path / "plugins"
    from alterego_training_hub.plugin_market import install_market_entry
    target = install_market_entry(entries[0], plugins_dir)
    assert target.exists()




def test_font_detection_priority():
    ui, mono = detect_fonts(["Segoe UI", "Inter", "Consolas",
                             "JetBrains Mono"])
    assert ui == "Inter" and mono == "JetBrains Mono"
    ui, mono = detect_fonts(["Arial"])
    assert ui == "Segoe UI" and mono == "Consolas"
    fonts = set_fonts("Inter", "JetBrains Mono")
    assert fonts["F_MONO"][0] == "JetBrains Mono"
    assert fonts["F_TITLE"][1] == 14
    set_fonts("Segoe UI", "Consolas")  # restore defaults for other tests
