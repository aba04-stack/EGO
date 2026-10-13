"""Tests for the cloud training job queue (RunPod flow, offline)."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.cloud_queue import (
    CloudJob,
    CloudJobQueue,
    CloudQueueError,
)


class FakePodClient:
    def __init__(self, fail=False, pods=None):
        self.fail = fail
        self.pods = pods or []
        self.plans = []

    def create_pod(self, plan, *, confirmed=False):
        assert confirmed is True
        self.plans.append(plan)
        if self.fail:
            raise RuntimeError("нет квоты")
        return {"id": "pod-123"}

    def list_pods(self):
        return self.pods


def test_job_validation_and_lines():
    job = CloudJob(name="run", command="python train.py")
    job.validate()
    assert job.active and "run" in job.line()
    with pytest.raises(CloudQueueError):
        CloudJob(name="", command="x").validate()
    with pytest.raises(CloudQueueError):
        CloudJob(name="x", command="").validate()
    with pytest.raises(CloudQueueError):
        CloudJob(name="x", command="y", status="weird").validate()


def test_queue_crud(tmp_path):
    queue = CloudJobQueue(tmp_path)
    first = queue.add(CloudJob(name="a", command="echo a"))
    second = queue.add(CloudJob(name="b", command="echo b"))
    assert [job.name for job in queue.list()] == ["b", "a"]
    assert queue.next_pending().name == "a"  # FIFO: oldest pending first
    updated = queue.update(first.id, status="running")
    assert updated.status == "running"
    assert queue.get(first.id).status == "running"

    cancelled = queue.cancel(second.id)
    assert cancelled.status == "cancelled"
    with pytest.raises(CloudQueueError):
        queue.cancel(second.id)  # already finished
    with pytest.raises(CloudQueueError):
        queue.get("missing")
    assert json.loads(queue.path.read_text(encoding="utf-8"))


def test_submit_and_sync(tmp_path):
    queue = CloudJobQueue(tmp_path)
    job = queue.add(CloudJob(name="train", command="python train.py",
                             gpu_type="RTX A4000"))
    client = FakePodClient()
    submitted = queue.submit(job.id, client)
    assert submitted.status == "submitted" and submitted.pod_id == "pod-123"
    assert client.plans[0]["command"] == "python train.py"
    assert client.plans[0]["gpu_type"] == "RTX A4000"

    synced = queue.sync(job.id, FakePodClient(
        pods=[{"id": "pod-123", "desiredStatus": "RUNNING"}]))
    assert synced.status == "running"
    lost = queue.sync(job.id, FakePodClient(pods=[]))
    assert lost.status == "failed" and "не найден" in lost.error

    job2 = queue.add(CloudJob(name="t2", command="c2"))
    queue.submit(job2.id, FakePodClient())
    exited = queue.sync(job2.id, FakePodClient(
        pods=[{"id": "pod-123", "desiredStatus": "EXITED"}]))
    assert exited.status == "done"

    failed_job = queue.add(CloudJob(name="x", command="y"))
    failed = queue.submit(failed_job.id, FakePodClient(fail=True))
    assert failed.status == "failed" and "нет квоты" in failed.error

    with pytest.raises(CloudQueueError):
        queue.submit(job.id, FakePodClient())  # already submitted
