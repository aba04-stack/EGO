"""Regression tests for the second external audit (points 29-38, v1.8.4)."""
from __future__ import annotations

import json
import types

import pytest

from alterego_training_hub.config import AppSettings
from alterego_training_hub.data_audit import audit_rows
from alterego_training_hub.resource_calc import GPU_CATALOG, estimate, throughput_tps
from alterego_training_hub.update_check import check_update, is_newer, parse_version


# 29: по умолчанию команды обучения НЕТ (а не pytest)
def test_default_training_command_is_empty():
    assert AppSettings().training_command == ""


# 30: prerelease не склеивается в числа и старше релиза быть не может
def test_version_prerelease():
    assert parse_version("1.2.3-rc1") == (1, 2, 3)
    assert is_newer("1.2.3", "1.2.3-rc1")
    assert not is_newer("1.2.3-rc1", "1.2.3")
    assert is_newer("1.2.3-rc2", "1.2.3-rc1")
    assert is_newer("1.2.4-rc1", "1.2.3")


# 31: 404 честно двусмыслен
def test_update_404_honest():
    def not_found(_url):
        raise OSError("HTTP Error 404: Not Found")
    text = check_update("1.0.0", fetcher=not_found).render()
    assert "приватный" in text and "404" in text


# 32: provider учитывается
def test_cloud_provider_routing(tmp_path):
    from alterego_training_hub.cloud_queue import (
        CloudJob,
        CloudJobQueue,
        CloudQueueError,
    )
    queue = CloudJobQueue(tmp_path)
    colab = queue.add(CloudJob(name="c", command="python t.py", provider="colab"))
    with pytest.raises(CloudQueueError, match="Colab"):
        queue.submit(colab.id, client=None)
    manual = queue.add(CloudJob(name="m", command="python t.py", provider="manual"))
    submitted = queue.submit(manual.id, client=None)
    assert submitted.status == "queued" and "Ручной провайдер" in submitted.log
    runpod = queue.add(CloudJob(name="r", command="python t.py", provider="runpod"))
    with pytest.raises(CloudQueueError, match="RunPod"):
        queue.submit(runpod.id, client=None)


# 33: битый settings.json не проглатывается молча; типы проверяются
def test_settings_corrupt_and_types(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{битый json", encoding="utf-8")
    loaded = AppSettings.load(path)
    assert loaded.load_error and "повреждён" in loaded.load_error
    assert list(tmp_path.glob("settings.json.corrupt-*"))  # копия сохранена
    path.write_text(json.dumps({
        "mentor_max_tokens": "не число", "mentor_temperature": "0.7",
        "ui_theme": 42, "night_watch_enabled": True}), encoding="utf-8")
    loaded = AppSettings.load(path)
    assert loaded.mentor_max_tokens == 1200          # умолчание вместо мусора
    assert loaded.mentor_temperature == 0.7          # строка-число приведена
    assert loaded.ui_theme == "light"
    assert loaded.night_watch_enabled is True
    assert "mentor_max_tokens" in loaded.load_error


# 37: GitHub/HF/AWS токены ловятся аудитом
@pytest.mark.parametrize("secret", [
    "ghp_1234567890abcdefghij1234567890",
    "hf_1234567890abcdefghij1234",
    "AKIAIOSFODNN7EXAMPLE",
    "xoxb-1234567890-abcdefghij",
])
def test_secret_patterns(secret):
    report = audit_rows([{"text": f"вот ключ {secret} не палите пожалуйста"}])
    assert report.pii_hits == 1


# 38: пропускная способность учитывает seq/batch, отчёт честен про разброс
def test_throughput_factors():
    gpu = GPU_CATALOG[0]
    base = throughput_tps(gpu, 7_000_000_000)
    assert throughput_tps(gpu, 7_000_000_000, seq_len=8192) < base
    assert throughput_tps(gpu, 7_000_000_000, batch=2) < base
    est = estimate(params=124_000_000, data_tokens=1_000_000, epochs=1)
    assert "1.5–2 раза" in est.render()


# 35: SSH run читает оба потока и не вешается на большом выводе
def test_ssh_run_drains_both_streams():
    import io

    from alterego_training_hub.servers import SshRunner

    class FakeStdout(io.BytesIO):
        def __init__(self, data):
            super().__init__(data)
            self.channel = types.SimpleNamespace(
                recv_exit_status=lambda: 0, close=lambda: None)

    runner = SshRunner("h", 22, "u")
    out = FakeStdout(b"x" * 300_000)
    err = FakeStdout(b"e" * 1000)

    class FakeClient:
        def exec_command(self, command, timeout=60.0):
            return io.BytesIO(), out, err

    runner._client = FakeClient()
    result = runner.run("big")
    assert result["ok"] and result["exit_code"] == 0
    assert "обрезано" in result["output"]  # сверх лимита честно помечено
