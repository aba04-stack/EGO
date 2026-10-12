from alterego_training_hub.metrics import brief, parse_log

SAMPLE = """
Epoch 1/10: train_loss=2.50 val_loss=2.40 acc=0.10 lr=1e-3
step 100 [10/1000] loss=2.31 acc=0.15
Epoch 2/10: train_loss=1.90 val_loss=1.85 acc=0.22
Epoch 3/10: train_loss=1.40 val_loss=1.50 acc=0.31
Epoch 4/10: train_loss=1.10 val_loss=1.20 acc=0.40
Epoch 5/10: train_loss=0.90 val_loss=1.00 acc=0.47
"""


def test_parse_extracts_series_progress_and_best():
    summary = parse_log(SAMPLE)
    assert summary.epoch_current == 5
    assert summary.epochs_total == 10
    assert summary.progress_ratio == 0.5
    assert summary.last["val_loss"] == 1.00
    assert summary.best["val_loss"] == 1.20 or summary.best["val_loss"] == 1.00
    assert summary.best["acc"] == 0.47
    assert "loss" in summary.last or "train_loss" in summary.last
    assert summary.primary_key in {"val_loss", "train_loss", "loss"}
    assert len(summary.series("acc")) >= 5
    assert "эпоха" in brief(summary) or "метрик" not in brief(summary)


def test_trend_direction():
    improving = parse_log("loss=2.0\nloss=1.5\nloss=1.0\nloss=0.6\nloss=0.4\n")
    assert improving.trend["loss"] == "улучшается"
    worsening = parse_log("loss=0.4\nloss=0.6\nloss=1.0\nloss=1.6\nloss=2.2\n")
    assert worsening.trend["loss"] == "ухудшается"
    flat = parse_log("loss=0.5\nloss=0.5\nloss=0.5\nloss=0.5\n")
    assert flat.trend["loss"] == "стабильно"


def test_anomalies_detect_divergence_and_nan():
    diverging = parse_log("loss=0.5\nloss=0.7\nloss=1.2\nloss=3.5\n")
    assert any("расходим" in item.lower() or "вырос" in item for item in diverging.anomalies)

    nan_log = "step 3 loss=nan acc=0.2\nstep 4 loss=0.5 acc=0.2\n"
    summary = parse_log(nan_log)
    assert any("NaN" in item for item in summary.anomalies)


def test_stagnation_and_empty_log():
    stagnant = parse_log("loss=0.5\nloss=0.5\nloss=0.5\nloss=0.5\nloss=0.5\nloss=0.5\n")
    assert any("стагнация" in item for item in stagnant.anomalies)

    empty = parse_log("hello world\nno numbers here\n")
    assert empty.last == {}
    assert empty.primary_key is None
    assert "нет" in brief(empty)


def test_ignores_noise_keys():
    summary = parse_log("Epoch 1/2 it/s: 3.5 time=12.3 loss=1.0 lr=0.1")
    assert "loss" in summary.last
    assert "lr" in summary.last
    assert "it" not in summary.last and "time" not in summary.last
    assert "epoch" not in summary.last
