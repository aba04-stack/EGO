import json
from typing import ClassVar

from alterego_training_hub.playground import (
    PlaygroundClient,
    PlaygroundResult,
    PlaygroundStore,
)


class FakeResponse:
    headers: ClassVar[dict] = {}

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return json.dumps(self._payload).encode("utf-8")


def test_generate_single_model(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        assert body["messages"][-1]["content"] == "Объясни attention."
        assert body["temperature"] == 0.3
        return FakeResponse({
            "model": "gpt-test",
            "choices": [{"message": {"content": "Attention — это …"}}],
            "usage": {"total_tokens": 10},
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = PlaygroundClient("https://api.example.test/v1", "gpt-test", "key")
    result = client.generate("Объясни attention.", system="Ты преподаватель.",
                             temperature=0.3, max_tokens=64)
    assert result.ok()
    assert result.output == "Attention — это …"
    assert result.model == "gpt-test"
    assert result.latency_ms >= 0


def test_generate_records_errors_without_raising(monkeypatch):
    import urllib.error

    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = PlaygroundClient("https://api.example.test/v1", "gpt-test", "key")
    result = client.generate("привет")
    assert not result.ok()
    assert "Could not connect" in result.error


def test_store_roundtrip(tmp_path):
    store = PlaygroundStore(tmp_path / "playground.jsonl")
    store.save(PlaygroundResult(model="m1", prompt="q", output="a", latency_ms=12,
                                temperature=0.5, max_tokens=10))
    store.save(PlaygroundResult(model="m2", prompt="q2", output="", latency_ms=30,
                                temperature=0.5, max_tokens=10, error="boom"))
    recent = store.recent()
    assert [item.model for item in recent] == ["m2", "m1"]
    assert recent[0].error == "boom"
    assert recent[1].ok()
