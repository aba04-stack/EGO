"""Этап F: stop != terminate — подтверждение опросом, учёт дисков (мок API)."""
from __future__ import annotations

from alterego_training_hub.cloud_gpu import RunPodClient


def _client(monkeypatch, states: list):
    """states: список ответов list_pods по опросам."""
    provider = RunPodClient(api_key="fake")
    calls = {"requests": [], "poll": 0}
    seq = list(states)

    def fake_request(method, path, payload=None, query=None):
        calls["requests"].append((method, path))
        return {"ok": True}

    def fake_list():
        calls["poll"] += 1
        return seq.pop(0) if seq else []

    monkeypatch.setattr(provider, "_request", fake_request)
    monkeypatch.setattr(provider, "list_pods", fake_list)
    return provider, calls


def test_stop_verified_when_exited(monkeypatch):
    provider, _ = _client(monkeypatch, [
        [{"id": "p1", "desiredStatus": "RUNNING"}],
        [{"id": "p1", "desiredStatus": "EXITED",
          "containerDiskInGb": 40}],
    ])
    result = provider.pod_action("p1", "stop", confirmed=True,
                                 sleep=lambda _: None)
    check = result["verification"]
    assert check["confirmed"] is True
    assert check["final_status"] == "EXITED"
    assert check["disk"]["container_disk_gb"] == 40.0


def test_terminate_needs_disappearance_not_status_word(monkeypatch):
    # под висит в TERMINATED-переходном виде, затем исчезает: только
    # исчезновение (или TERMINATED) подтверждает; RUNNING — нет
    provider, _ = _client(monkeypatch, [
        [{"id": "p1", "desiredStatus": "RUNNING", "volumeInGb": 100}],
        [{"id": "p1", "desiredStatus": "RUNNING"}],
        [],
    ])
    result = provider.terminate_pod("p1", confirmed=True,
                                    sleep=lambda _: None)
    check = result["verification"]
    assert check["confirmed"] is True
    assert check["final_status"] == "ABSENT"
    assert "сетевые тома" in check["note"]
    assert result["disk_before"]["volume_gb"] == 100.0


def test_unconfirmed_state_is_honest(monkeypatch):
    provider, _ = _client(monkeypatch, [
        [{"id": "p1", "desiredStatus": "RUNNING"}]] * 8)
    result = provider.pod_action("p1", "stop", confirmed=True,
                                 sleep=lambda _: None)
    check = result["verification"]
    assert check["confirmed"] is False
    assert "НЕ подтверждено" in check["note"]


def test_poll_errors_do_not_fake_confirmation(monkeypatch):
    provider = RunPodClient(api_key="fake")
    monkeypatch.setattr(provider, "_request",
                        lambda *a, **k: {"ok": True})

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(provider, "list_pods", boom)
    result = provider.pod_action("p1", "stop", confirmed=True,
                                 sleep=lambda _: None)
    assert result["verification"]["confirmed"] is False
