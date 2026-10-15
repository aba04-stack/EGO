"""Stage 21 — full-pipeline integration plus regressions for audited bugs.

Pipeline: template project → real training run with hot control.json →
metrics → evaluation → watchdog → tuning suggestions → report export →
cloud queue plan (RunPod shape).
"""
from __future__ import annotations

import json
import subprocess
import sys

from alterego_training_hub.cloud_queue import CloudJob, CloudJobQueue
from alterego_training_hub.evaluation import build_eval_report
from alterego_training_hub.hparam_tuning import apply_suggestions, suggest_fixes
from alterego_training_hub.metrics import parse_log
from alterego_training_hub.report_export import ReportContext, _inline, save_report
from alterego_training_hub.templates import create_project
from alterego_training_hub.training import read_control, write_control
from alterego_training_hub.watchdog import TrainingWatchdog

# Non-contiguous epochs (restarted run): best at epoch 5, worsens at 6.
OVERFIT_LOG = (
    "epoch 1/8 loss=3.00 val_loss=3.00\n"
    "epoch 5/8 loss=2.00 val_loss=2.00\n"
    "epoch 6/8 loss=1.00 val_loss=2.80\n"
)

# Best has train_loss == 0.0 and later train got WORSE: not overfitting.
FLAT_TRAIN_LOG = (
    "epoch 1/8 loss=3.00 val_loss=3.00\n"
    "epoch 5/8 loss=0.00 val_loss=2.00\n"
    "epoch 6/8 loss=0.50 val_loss=2.80\n"
)


def test_full_pipeline_template_to_report(tmp_path):
    # 1. Template project + hot control: cap epochs via control.json.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    create_project(workspace, "demo", "minimal-lm")
    project = workspace / "demo"
    write_control(project, {"max_epochs": 2})
    assert read_control(project)["max_epochs"] == 2
    result = subprocess.run([sys.executable, "train.py"], cwd=project,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0
    log = result.stdout
    assert "checkpoint saved" in log

    # 2. Metrics parsed from the live training log.
    summary = parse_log(log)
    assert summary.epoch_current == 2
    assert "loss" in summary.last and "val_loss" in summary.last

    # 3. Evaluation: best epoch found, healthy curve has no overfitting.
    report = build_eval_report(log)
    assert report.best_epoch is not None
    assert report.overfitting is False
    assert report.lines()

    # 4. Watchdog runs over the same summary without a false alarm.
    watchdog = TrainingWatchdog()
    evaluated = watchdog.evaluate(summary, running=True)
    assert evaluated.issues is not None
    assert all(issue.code != "overfitting" for issue in evaluated.issues)

    # 5. Tuning proposes control fixes and applies them.
    suggestions = suggest_fixes(summary, {"lr": 0.05})
    assert suggestions
    assert suggestions[0].param in {"lr", "grad_clip", "early_stop_patience"}
    fixed = apply_suggestions({"lr": 0.05}, suggestions)
    assert isinstance(fixed, dict) and "lr" in fixed

    # 6. Report export creates parent dirs (regression).
    context = ReportContext(
        title="Обучение demo",
        model_info={"name": "minimal-lm"},
        metrics_lines=[f"{key}: {value:.4f}"
                       for key, value in sorted(summary.last.items())],
        eval_lines=report.lines(),
    )
    out_dir = tmp_path / "reports" / "nested"
    exported = save_report(out_dir / "Обучение demo.md", context, fmt="md")
    assert exported.path.endswith(".md")
    assert (out_dir / "Обучение demo.md").exists()

    # 7. Cloud queue plan matches RunPodClient.create_pod exactly.
    class RecordingClient:
        plan = None

        def create_pod(self, plan, *, confirmed):
            self.plan = plan
            return {"id": "pod-1"}

    queue = CloudJobQueue(tmp_path / "library")
    job = queue.add(CloudJob(name="дообучение", command="python train.py",
                             gpu_id="NVIDIA RTX A4000",
                             max_gpu_hourly_usd=0.4))
    client = RecordingClient()
    queued = queue.submit(job.id, client)
    assert queued.status == "submitted"
    assert {"name", "gpu_id", "gpu_only_budget_usd", "cloud", "image",
            "container_disk_gb", "command"} <= set(client.plan)
    assert client.plan["gpu_id"] == "NVIDIA RTX A4000"
    assert client.plan["gpu_only_budget_usd"] == 0.4
    raw = json.loads((project / "control.json").read_text(encoding="utf-8"))
    assert raw["max_epochs"] == 2  # control.json survived the run


def test_overfitting_on_noncontiguous_epochs():
    report = build_eval_report(OVERFIT_LOG)
    assert report.best_epoch == 5
    assert report.overfitting is True  # old slicing points[5:] missed epoch 6


def test_overfitting_requires_train_improvement():
    report = build_eval_report(FLAT_TRAIN_LOG)
    assert report.best_epoch == 5
    # 0.50 < 0.00 is False — `or float("inf")` used to call this overfitting.
    assert report.overfitting is False


def test_hotkey_case_variants_cover_shift_letters():
    from alterego_training_hub.hotkeys import case_variants

    assert case_variants("<Control-Shift-M>") == \
        ["<Control-Shift-M>", "<Control-Shift-m>"]
    assert case_variants("<Control-Shift-F>") == \
        ["<Control-Shift-F>", "<Control-Shift-f>"]
    assert case_variants("<Control-p>") == ["<Control-p>"]
    assert case_variants("<F5>") == ["<F5>"]


def test_version_is_templated_and_package_version_readable():
    from alterego_training_hub import __version__
    from alterego_training_hub.i18n import current_language, set_language, t

    assert __version__.count(".") >= 2
    previous = current_language()
    try:
        for lang in ("ru", "en"):
            set_language(lang)
            text = t("brand.version")
            assert "{version}" in text
            assert __version__ in text.format(version=__version__)
    finally:
        set_language(previous)


def test_report_inline_keeps_underscores():
    assert _inline("train_loss **0.5**") == "train_loss 0.5"
