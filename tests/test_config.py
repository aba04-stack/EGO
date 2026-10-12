import json

from alterego_training_hub.config import AppSettings, SecretStore


def test_settings_save_load_without_secrets(tmp_path):
    path = tmp_path / "settings.json"
    settings = AppSettings(
        repo_path="/work/model",
        mentor_base_url="https://api.example.test/v1",
        mentor_model="mentor",
        runpod_max_gpu_hourly_usd=0.8,
    )
    settings.save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(raw).lower()
    loaded = AppSettings.load(path)
    assert loaded.repo_path == settings.repo_path
    assert loaded.mentor_model == "mentor"
    assert loaded.runpod_max_gpu_hourly_usd == 0.8


def test_secret_store_uses_keyring_not_plaintext_files(monkeypatch, tmp_path):
    import keyring

    values = {}
    monkeypatch.setattr(keyring, "set_password", lambda service, name, value: values.__setitem__((service, name), value))
    monkeypatch.setattr(keyring, "get_password", lambda service, name: values.get((service, name)))
    monkeypatch.setattr(keyring, "delete_password", lambda service, name: values.pop((service, name), None))

    store = SecretStore(service="test-app")
    store.set("mentor_api_key", "not-for-logs")
    assert store.get("mentor_api_key") == "not-for-logs"
    store.delete("mentor_api_key")
    assert store.get("mentor_api_key") == ""
    assert values == {}
