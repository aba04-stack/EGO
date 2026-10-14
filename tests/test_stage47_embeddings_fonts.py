"""Этап 47: API-эмбеддинги в поиске, инвалидация кэша, комплектные шрифты."""
from pathlib import Path

from alterego_training_hub.semantic_search import (
    ApiEmbedder,
    HashEmbedder,
    SemanticIndex,
)
from alterego_training_hub.theme import bundled_fonts_dir, register_bundled_fonts


def test_embedder_ids_differ():
    assert HashEmbedder().id != ApiEmbedder("https://x", "m").id
    assert ApiEmbedder("https://x", "a").id != ApiEmbedder("https://x", "b").id


def test_cache_invalidated_by_embedder_switch(tmp_path):
    (tmp_path / "a.py").write_text("train loss loop epoch\n" * 5,
                                   encoding="utf-8")
    first = SemanticIndex(tmp_path, HashEmbedder(dim=32))
    first.build()
    cached = first.to_cache()
    calls = []

    def fake_embedder(texts):
        calls.append(len(texts))
        return [[1.0, 0.0] for _ in texts]

    fake_embedder.id = "api:other"  # type: ignore[attr-defined]
    second = SemanticIndex(tmp_path, fake_embedder)
    stats = second.build(cached)
    assert stats["embedded"] >= 1 and calls  # rebuilt, not reused
    assert second.embedder_id == "api:other"


def test_bundled_fonts_ship_with_package():
    fonts = bundled_fonts_dir()
    assert (fonts / "Inter.ttf").exists()
    assert (fonts / "JetBrainsMono.ttf").exists()
    assert (fonts / "OFL-Inter.txt").exists()


def test_register_bundled_fonts_linux_copies(tmp_path, monkeypatch):

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    placed = register_bundled_fonts()
    target = home / ".local" / "share" / "fonts" / "alterego"
    assert (target / "Inter.ttf").exists()
    assert len(placed) == 2
    # idempotent second call
    assert len(register_bundled_fonts()) == 2
