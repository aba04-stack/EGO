"""Этап 40: семантический поиск — эмбеддинги, чанки, кэш, ранжирование."""
import json

from alterego_training_hub.semantic_search import (
    ApiEmbedder,
    HashEmbedder,
    SemanticIndex,
    chunk_text,
    cosine,
)


def test_hash_embedder_deterministic_and_normalized():
    embedder = HashEmbedder(dim=64)
    a, b = embedder(["train loop loss", "train loop loss"])
    assert a == b
    assert abs(sum(v * v for v in a) ** 0.5 - 1.0) < 1e-6
    assert cosine(a, a) > 0.99


def test_chunk_text_windows():
    text = "\n".join(f"line {i}" for i in range(100))
    chunks = chunk_text("a.py", text)
    assert chunks[0].line == 1
    assert all(c.path == "a.py" for c in chunks)
    assert len(chunks) >= 3


def _workspace(tmp_path):
    (tmp_path / "train.py").write_text(
        "def train_loop(model, data):\n"
        "    for epoch in range(10):\n"
        "        loss = model.step(data)\n"
        "        print('epoch loss', loss)\n" * 3, encoding="utf-8")
    (tmp_path / "ui.py").write_text(
        "def render_button(label):\n"
        "    return Button(text=label, color='blue')\n" * 3,
        encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x.py").write_text("loss = 1\n", encoding="utf-8")
    return tmp_path


def test_index_search_ranks_relevant_first(tmp_path):
    index = SemanticIndex(_workspace(tmp_path))
    stats = index.build()
    assert stats["files"] == 2  # .git ignored
    hits = index.search("training loop epoch loss")
    assert hits and hits[0].path == "train.py"


def test_index_cache_reuse_and_invalidation(tmp_path, tmp_path_factory):
    root = _workspace(tmp_path)
    cache = tmp_path_factory.mktemp("c") / "idx.json"
    first = SemanticIndex(root)
    first.build()
    first.save(cache)
    second = SemanticIndex(root)
    stats = second.build(SemanticIndex.load_cache(cache))
    assert stats["reused"] == 2 and stats["embedded"] == 0
    (root / "train.py").write_text("loss = 42\n", encoding="utf-8")
    third = SemanticIndex(root)
    stats = third.build(SemanticIndex.load_cache(cache))
    assert stats["embedded"] >= 1


def test_api_embedder_batches_and_sorts():
    def fake_transport(url, headers, payload):
        assert url.endswith("/embeddings")
        return {"data": [{"index": i, "embedding": [float(i), 1.0]}
                         for i in reversed(range(len(payload["input"])))]}

    embedder = ApiEmbedder("https://api.example/v1", "emb-1",
                           transport=fake_transport)
    vectors = embedder(["a", "b", "c"])
    assert vectors == [[0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]


def test_cache_file_is_json(tmp_path):
    index = SemanticIndex(_workspace(tmp_path))
    index.build()
    target = tmp_path / "idx.json"
    index.save(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["chunks"]
