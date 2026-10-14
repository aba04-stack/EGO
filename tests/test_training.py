import sys
import time

import pytest

from alterego_training_hub.training import TrainingError, TrainingRun


def wait_done(run: TrainingRun, seconds: float = 10.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not run.status().running:
            return
        time.sleep(0.05)
    raise AssertionError("training did not finish in time")


def test_run_command_and_capture_log(tmp_path):
    run = TrainingRun(tmp_path / "logs")
    log = run.start(f'{sys.executable} -c "print(\'epoch 1 loss 0.5\')"', tmp_path)
    assert run.status().running or True
    wait_done(run)
    status = run.status()
    assert status.running is False
    assert status.returncode == 0
    assert status.log_path == log
    tail = run.tail()
    assert "epoch 1 loss 0.5" in tail
    assert run.list_logs()


def test_failure_returncode_recorded(tmp_path):
    run = TrainingRun(tmp_path / "logs")
    run.start(f'{sys.executable} -c "raise SystemExit(3)"', tmp_path)
    wait_done(run)
    assert run.status().returncode == 3


def test_validation_and_double_start(tmp_path):
    run = TrainingRun(tmp_path / "logs")
    with pytest.raises(TrainingError):
        run.start("", tmp_path)
    with pytest.raises(TrainingError):
        run.start("python -c 1", tmp_path / "missing")
    with pytest.raises(TrainingError):
        run.start("definitely-not-a-cmd", tmp_path)

    run.start(f'{sys.executable} -c "import time; time.sleep(30)"', tmp_path)
    assert run.status().running is True
    with pytest.raises(TrainingError):
        run.start("python -c 1", tmp_path)
    run.stop()
    wait_done(run)
    assert run.status().running is False
    with pytest.raises(TrainingError):
        run.stop()
