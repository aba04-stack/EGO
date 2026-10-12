import pytest

from alterego_training_hub.cloud_gpu import CloudGpuError, RunPodClient


def client():
    return RunPodClient(api_key="fake-test-key")


def fake_catalog(**kwargs):
    return [{
        "id": "GPU_TEST",
        "name": "Test GPU",
        "memory": 24,
        "price": {"secure": 0.45, "community": 0.25},
        "availability": "HIGH",
    }]


def test_gpu_price_limit_and_plan(monkeypatch):
    provider = client()
    monkeypatch.setattr(provider, "gpu_catalog", fake_catalog)
    plan = provider.plan_pod(
        gpu_id="GPU_TEST",
        max_gpu_hourly_usd=0.50,
        cloud="SECURE",
        container_disk_gb=30,
    )
    assert plan["gpu_hourly_usd"] == 0.45
    assert plan["gpu_name"] == "Test GPU"
    assert "not a total" not in plan["warning"].lower()  # warning is explicit about other charges

    with pytest.raises(CloudGpuError, match="exceeds"):
        provider.plan_pod(
            gpu_id="GPU_TEST",
            max_gpu_hourly_usd=0.30,
            cloud="SECURE",
        )


def test_refuses_gpu_missing_from_live_catalog(monkeypatch):
    provider = client()
    monkeypatch.setattr(provider, "gpu_catalog", lambda **kwargs: [])
    with pytest.raises(CloudGpuError, match="no longer present"):
        provider.plan_pod(gpu_id="MISSING", max_gpu_hourly_usd=1.0)


def test_provisioning_requires_explicit_confirmation():
    provider = client()
    with pytest.raises(CloudGpuError, match="explicit confirmation"):
        provider.create_pod({"gpu_id": "GPU_TEST"}, confirmed=False)


def test_stop_and_termination_require_confirmation():
    provider = client()
    with pytest.raises(CloudGpuError, match="confirmation"):
        provider.pod_action("pod-1", "stop")
    with pytest.raises(CloudGpuError, match="confirmation"):
        provider.terminate_pod("pod-1")


@pytest.mark.parametrize("pod_id", ["", "../other", "folder/pod", "pod\nid"])
def test_rejects_invalid_pod_ids(pod_id):
    with pytest.raises(CloudGpuError):
        RunPodClient._path_id(pod_id)
