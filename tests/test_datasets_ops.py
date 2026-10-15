"""Tests for dataset operations: split, filter, write/read, Hugging Face fetch."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from alterego_training_hub.datasets import (
    DatasetError,
    fetch_hf_rows,
    filter_rows,
    read_rows,
    split_rows,
    write_rows,
)


def _rows(n=10):
    return [{"text": f"строка {i}", "id": i} for i in range(n)]


def test_split_rows_ratios_and_seed():
    rows = _rows(10)
    parts = split_rows(rows, train=0.8, val=0.1, test=0.1, seed=7)
    assert len(parts["train"]) == 8
    assert len(parts["val"]) + len(parts["test"]) == 2
    ids = [row["id"] for part in parts.values() for row in part]
    assert sorted(ids) == list(range(10))  # partition, no drops/dupes
    again = split_rows(rows, train=0.8, val=0.1, test=0.1, seed=7)
    assert again == parts  # deterministic

    single = split_rows(_rows(1))
    assert len(single["train"]) == 1
    assert split_rows([]) == {"train": [], "val": [], "test": []}
    with pytest.raises(DatasetError):
        split_rows(rows, train=0, val=0, test=0)


def test_filter_rows_rules():
    rows = [{"text": "alpha beta"}, {"text": "beta"}, {"text": "gamma"},
            {"text": ""}]
    assert len(filter_rows(rows, contains="beta")) == 2
    assert len(filter_rows(rows, excludes="beta")) == 2
    assert len(filter_rows(rows, min_chars=5)) == 2
    assert len(filter_rows(rows, max_chars=4)) == 2
    assert filter_rows(rows, field="missing") == rows  # empty text passes


def test_write_and_read_roundtrip(tmp_path):
    rows = [{"text": "привет", "n": 1}, {"text": "мир", "n": 2}]
    for fmt in ("jsonl", "json", "csv", "tsv", "txt"):
        path = write_rows(tmp_path / f"data.{fmt}", rows, fmt)
        assert path.exists()
        loaded = read_rows(path, fmt)
        assert len(loaded) == 2
    with pytest.raises(DatasetError):
        write_rows(tmp_path / "data.parquet", rows, "parquet")


def test_fetch_hf_rows_parses_response(monkeypatch):
    payload = json.dumps({"rows": [
        {"row": {"text": "вопрос-ответ"}}, {"row": {"text": "второй"}},
    ]}).encode()

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    calls = {}

    def fake_urlopen(request, timeout=None):
        calls["url"] = request.full_url
        return FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    rows = fetch_hf_rows("org/name", split="validation", limit=2)
    assert len(rows) == 2 and rows[0]["text"] == "вопрос-ответ"
    assert "datasets-server.huggingface.co" in calls["url"]
    assert "split=validation" in calls["url"]


def test_fetch_hf_rows_validation_and_errors(monkeypatch):
    with pytest.raises(DatasetError):
        fetch_hf_rows("без слэша")
    with pytest.raises(DatasetError):
        fetch_hf_rows("org/name?x=1")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("no net")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(DatasetError):
        fetch_hf_rows("org/name")

    def fake_http(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_http)
    with pytest.raises(DatasetError):
        fetch_hf_rows("org/name")

    def fake_garbage(request, timeout=None):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return R(b"not json")

    monkeypatch.setattr("urllib.request.urlopen", fake_garbage)
    with pytest.raises(DatasetError):
        fetch_hf_rows("org/name")
