"""Третий аудит: облачный цикл, бюджет, сходимость (поведенческие тесты)."""
from __future__ import annotations

import pytest

from alterego_training_hub.budget_guard import BudgetLedger
from alterego_training_hub.cloud_gpu import RunPodClient
from alterego_training_hub.cloud_queue import CloudJob, CloudJobQueue, CloudQueueError
from alterego_training_hub.compare import compare_runs
from alterego_training_hub.metrics import MetricPoint, MetricsSummary


class FakeClient:
    def __init__(self, fail_terminate=False):
        self.fail_terminate = fail_terminate
        self.terminated = []

    def create_pod(self, plan, confirmed=False):
        return {"id": "pod-9", "confirmed_gpu_hourly_usd": 0.5}

    def list_pods(self):
        return [{"id": "pod-9", "desiredStatus": "RUNNING"}]

    def terminate_pod(self, pod_id, confirmed=False):
        if self.fail_terminate:
            raise RuntimeError("API недоступен")
        self.terminated.append(pod_id)
        return {"ok": True}


# 6: под из очереди помечается managed в журнале бюджета
def test_submit_marks_pod_managed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    queue = CloudJobQueue(tmp_path / "lib")
    job = queue.add(CloudJob(name="t", command="python train.py"))
    updated = queue.submit(job.id, FakeClient())
    assert updated.status == "submitted"
    ledger = BudgetLedger.load()
    assert ledger.pods["pod-9"].managed is True


# 6б: повреждённый budget.json сохраняется копией, не обнуляется молча
def test_budget_corrupt_preserved(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text("{битый", encoding="utf-8")
    ledger = BudgetLedger.load(path)
    assert ledger.load_error
    assert list(tmp_path.glob("budget.json.corrupt-*"))


# 7: неудавшаяся остановка пода — задание НЕ cancelled
def test_cancel_failure_keeps_job_active(tmp_path):
    queue = CloudJobQueue(tmp_path)
    job = queue.add(CloudJob(name="t", command="python train.py"))
    queue.submit(job.id, FakeClient())
    with pytest.raises(CloudQueueError, match="НЕ отменено"):
        queue.cancel(job.id, client=FakeClient(fail_terminate=True))
    assert queue.get(job.id).status == "submitted"
    ok = queue.cancel(job.id, client=FakeClient())
    assert ok.status == "cancelled"


# 7б: без клиента отмена локальная, но честно предупреждает про расходы
def test_cancel_without_client_warns(tmp_path):
    queue = CloudJobQueue(tmp_path)
    job = queue.add(CloudJob(name="t", command="python train.py"))
    queue.submit(job.id, FakeClient())
    cancelled = queue.cancel(job.id)
    assert "может продолжать работать" in cancelled.log


# 8: EXITED -> done, но с честной пометкой «успех не подтверждён»
def test_sync_exited_is_unverified_done(tmp_path):
    queue = CloudJobQueue(tmp_path)
    job = queue.add(CloudJob(name="t", command="python train.py"))
    queue.submit(job.id, FakeClient())
    done = queue.sync(job.id, FakeClient())
    # FakeClient.list_pods даёт RUNNING; подменим на EXITED
    class Exited(FakeClient):
        def list_pods(self):
            return [{"id": "pod-9", "desiredStatus": "EXITED"}]
    done = queue.sync(job.id, Exited())
    assert done.status == "done"
    assert "НЕ подтверждена" in done.log


# 1: create_pod шлёт dockerArgs строкой и подтверждает статус пода
def test_create_pod_payload_and_status(monkeypatch):
    client = RunPodClient("key")
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload or {})
        return {"id": "pod-1"}

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "plan_pod", lambda **kw: {
        "name": "n", "image": "img", "cloud": "SECURE",
        "container_disk_gb": 30, "gpu_id": "g1", "gpu_hourly_usd": 0.4,
        "warning": "w"})
    monkeypatch.setattr(client, "list_pods",
                        lambda: [{"id": "pod-1", "desiredStatus": "RUNNING"}])
    result = client.create_pod({"command": "python train.py"}, confirmed=True)
    assert captured["payload"]["dockerArgs"] == "python train.py"
    assert result["pod_status"] == "RUNNING"
    assert "не подтверждает" in result["command_status"]


# 10: сходимость считается по val_loss, когда сравнение идёт по ней
def _summary(series):
    points = [MetricPoint(step=i + 1, epoch=i + 1, values=v)
              for i, v in enumerate(series)]
    return MetricsSummary(points=points, last=dict(points[-1].values),
                          epoch_current=len(points), epochs_total=len(points))


def test_converge_uses_val_loss():
    a = _summary([{"loss": 0.1, "val_loss": 3.0},
                  {"loss": 0.05, "val_loss": 2.0},
                  {"loss": 0.01, "val_loss": 1.0}])
    b = _summary([{"loss": 3.0, "val_loss": 3.0},
                  {"loss": 2.0, "val_loss": 2.5},
                  {"loss": 1.0, "val_loss": 2.0}])
    report = compare_runs(a, b, label_a="A", label_b="B")
    # target по val_loss = 1.0: A достигает на эпохе 3 (по train loss было бы 1)
    assert report.converge_a == 3
