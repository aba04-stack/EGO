"""Tests for hot training control (control.json) and the template loop."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from alterego_training_hub.templates import create_project
from alterego_training_hub.training import (
    read_control,
    write_control,
)


def test_write_and_read_control_merge_and_validate(tmp_path):
    assert read_control(tmp_path) == {}
    current = write_control(tmp_path, {"lr": 0.01, "stop": True,
                                       "note": "дивергенция"})
    assert current["lr"] == 0.01 and current["stop"] is True
    current = write_control(tmp_path, {"max_epochs": 4})
    assert current["max_epochs"] == 4 and current["lr"] == 0.01  # merged
    with pytest.raises(Exception):
        write_control(tmp_path, {"hack": 1})  # unknown key rejected
    raw = json.loads((tmp_path / "control.json").read_text(encoding="utf-8"))
    assert raw["note"] == "дивергенция"


def test_template_training_honours_hot_control(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    created = create_project(workspace, "demo", "minimal-lm")  # noqa: F841
    project = workspace / "demo"
    assert (project / "train.py").exists()

    # 1) stop flag: training halts on the first epoch and consumes the flag.
    (project / "control.json").write_text(
        json.dumps({"stop": True, "note": "ручная остановка"}),
        encoding="utf-8")
    result = subprocess.run([sys.executable, "train.py"], cwd=project,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    assert "training stopped by control.json: ручная остановка" in result.stdout
    assert "epoch 2/" not in result.stdout
    control = json.loads((project / "control.json").read_text(encoding="utf-8"))
    assert control["stop"] is False  # consumed

    # 2) max_epochs override: config asks 30, control caps at 2.
    (project / "control.json").write_text(
        json.dumps({"max_epochs": 2}), encoding="utf-8")
    result = subprocess.run([sys.executable, "train.py"], cwd=project,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    epochs = [line for line in result.stdout.splitlines()
              if line.startswith("epoch ")]
    assert len(epochs) == 2

    # 3) early stop via patience with a flat loss curve.
    (project / "control.json").write_text(
        json.dumps({"early_stop_patience": 1}), encoding="utf-8")
    result = subprocess.run([sys.executable, "train.py"], cwd=project,
                            capture_output=True, text=True, timeout=60)
    assert "early stop" in result.stdout or "epoch 30/" in result.stdout
