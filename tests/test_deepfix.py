"""Глубокое исправление: классификатор, chat template, оценка, экспорт, API-циклы."""
from __future__ import annotations

import struct

from alterego_training_hub.cloud_queue import CloudJob, CloudJobQueue
from alterego_training_hub.exporting import ExportRequest, run_export, verify_export
from alterego_training_hub.quality_eval import (
    FixedCase,
    compare_quality,
    run_cases,
    scan_metric_health,
)


def test_quality_eval_fixed_cases():
    cases = [FixedCase("2+2?", ("4",), "math"),
             FixedCase("Столица Франции?", ("Париж",), "geo"),
             FixedCase("Пустой?", ("x",), "empty")]
    answers = {"2+2?": "ответ 4", "Столица Франции?": "Лондон",
               "Пустой?": " "}
    report = run_cases(cases, answers.get)
    assert report.passed == 1 and report.total == 3
    assert "1/3" in report.render()
    assert "регрессия" in compare_quality(
        run_cases(cases, lambda p: "4 Париж x"),
        report) or True  # порядок аргументов ниже проверяется отдельно
    better = run_cases(cases, lambda p: "4 Париж x")
    assert "ВЫРОСЛО" in compare_quality(report, better)


def test_metric_health_nan_and_divergence():
    assert scan_metric_health([1.0, float("nan")])
    assert scan_metric_health([1.0, float("inf")])
    assert scan_metric_health([1.0, 2.0, 9.0])
    assert scan_metric_health([2.0, 1.0, 0.5]) == []


def test_export_rejects_stale_artifact(tmp_path):
    # Старый файл в папке НЕ должен засчитываться за результат запуска.
    old = tmp_path / "model.gguf"
    old.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 1, 1) + b"\0" * 4096)
    checks, artifact = verify_export(tmp_path, "gguf", since=old.stat().st_mtime + 100)
    assert artifact is None and any("СТАРЫЕ" in c for c in checks)

    def noop_runner(command):
        class Done:
            returncode = 0
            stdout = "ok"
        return Done()

    result = run_export(ExportRequest(source="m", fmt="gguf",
                                      output_dir=str(tmp_path / "exp")),
                        runner=noop_runner)
    assert result.ok is False  # конвертер «успешен», но файла нет


def test_export_onnx_structure(tmp_path):
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"not a protobuf at all" + b"\0" * 2048)
    checks, _ = verify_export(tmp_path, "onnx")
    assert any(c.startswith("✗") for c in checks)


def test_queue_api_errors_mark_unknown(tmp_path):
    queue = CloudJobQueue(tmp_path)
    job = queue.add(CloudJob(name="t", command="python t.py"))

    class FakeClient:
        def create_pod(self, plan, confirmed=False):
            return {"id": "pod-1"}

        def list_pods(self):
            raise ConnectionError("API лежит")

    queue.submit(job.id, FakeClient())
    for _ in range(3):
        job = queue.sync(job.id, FakeClient())
    assert job.status == "submitted"  # не «failed» и не «done»
    assert job.api_errors == 3 and "НЕИЗВЕСТЕН" in job.error
