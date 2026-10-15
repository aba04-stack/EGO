import time

from alterego_training_hub.runs import RunStore


def test_run_lifecycle(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    record = store.start("python train.py", "/work", "log.txt")
    assert record.running is True
    assert store.latest_running().id == record.id

    store.finish(record.id, returncode=0, metrics_last={"loss": 0.4},
                 best={"loss": 0.35}, anomalies=["внимание"])
    loaded = store.list()[0]
    assert loaded.running is False
    assert loaded.returncode == 0
    assert loaded.status_ru == "успешно"
    assert loaded.metrics_last["loss"] == 0.4
    assert loaded.anomalies == ["внимание"]

    store.attach_score(record.id, 7.5)
    assert store.list()[0].analysis_score == 7.5


def test_start_closes_dangling_runs_and_caps_history(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    first = store.start("cmd1", "/w")
    second = store.start("cmd2", "/w")
    records = store.list()
    assert records[0].id == second.id
    assert records[1].running is False  # dangling run auto-closed
    assert records[1].id == first.id

    for i in range(60):
        store.start(f"cmd-{i}", "/w")
    assert len(store.list(limit=100)) <= store.MAX_RUNS


def test_finish_unknown_record_returns_none(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    assert store.finish("missing", 0) is None
    time.sleep(0)
