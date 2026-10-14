"""Tests for Colab notebook export from cloud jobs."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.cloud_queue import CloudJob, CloudJobQueue
from alterego_training_hub.colab_export import (ColabExportError,
                                                default_notebook_name,
                                                export_queue,
                                                notebook_for_job,
                                                save_notebook)


def _job(name="дообучение-gpt2"):
    return CloudJob(name=name, command="python train.py --steps 100",
                    gpu_id="NVIDIA RTX A4000",
                    image="runpod/pytorch:2.8.0-py3.11-cuda12.8.1",
                    container_disk_gb=30)


def test_notebook_structure():
    notebook = notebook_for_job(_job())
    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"
    assert notebook["metadata"]["colab"]["provenance"] is False
    cells = notebook["cells"]
    assert len(cells) == 4
    assert cells[0]["cell_type"] == "markdown"
    assert "дообучение-gpt2" in "".join(cells[0]["source"])
    command_cell = "".join(cells[2]["source"])
    assert "!python train.py --steps 100" in command_cell
    assert "NVIDIA RTX A4000" in "".join(cells[1]["source"])
    for cell in cells[1:]:
        assert cell["cell_type"] == "code"
        assert cell["execution_count"] is None and cell["outputs"] == []


def test_save_notebook_creates_parents(tmp_path):
    job = _job()
    file = save_notebook(job, tmp_path / "exports" / "deep" / "run.ipynb")
    assert file.exists()
    raw = json.loads(file.read_text(encoding="utf-8"))
    assert raw["nbformat"] == 4
    with pytest.raises(ColabExportError):
        notebook_for_job({"not": "a job"})


def test_default_notebook_name_sanitized():
    job = _job(name="обучение/тест: v2")
    name = default_notebook_name(job)
    assert name.endswith(".ipynb")
    assert "/" not in name and ":" not in name
    assert name.startswith("colab-")


def test_export_queue_writes_all(tmp_path):
    queue = CloudJobQueue(tmp_path / "library")
    queue.add(_job("задание-1"))
    queue.add(_job("задание-2"))
    files = export_queue(queue, tmp_path / "colab")
    assert len(files) == 2
    for file in files:
        assert file.exists()
        assert json.loads(file.read_text(encoding="utf-8"))["nbformat"] == 4
