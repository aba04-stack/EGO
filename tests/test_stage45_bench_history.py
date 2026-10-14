"""Этап 45: история бенчмарков — дельты, сравнение, CSV, live-запись."""
import time

from alterego_training_hub.bench import BenchResult, BenchStore
from alterego_training_hub.bench_history import (
    compare_latest,
    history_table,
    latest_per_model,
    to_csv,
    with_deltas,
)
from alterego_training_hub.live_bench import LiveBenchReport, report_to_result


def _result(model, *, kind="live", passed=3, total=4, when=0.0, tps=0.0):
    return BenchResult(model=model, command="x", kind=kind, passed=passed,
                       total=total, tokens_per_sec=tps, created_at=when)


def test_deltas_against_previous_same_model():
    now = time.time()
    results = [_result("m1", passed=2, when=now - 100),
               _result("m1", passed=3, when=now - 50),
               _result("m2", passed=4, when=now - 10)]
    pairs = with_deltas(results)
    assert pairs[0][0].model == "m2"  # newest first
    assert pairs[1][1] != "—"  # newest m1 compares to its predecessor
    assert pairs[2][1] == "—"  # oldest m1 has none


def test_history_table_and_compare():
    now = time.time()
    results = [_result("alpha", passed=4, when=now - 5),
               _result("beta", passed=1, when=now - 3)]
    table = history_table(results)
    assert "alpha" in table and "4/4" in table
    lines = compare_latest(results)
    assert lines[0].startswith("alpha")
    assert latest_per_model(results)["beta|live"].passed == 1


def test_csv_export():
    text = to_csv([_result("m", when=time.time())])
    assert "passed" in text.splitlines()[0] and ",m," in text


def test_empty_history_message():
    assert "пуста" in history_table([])
    assert compare_latest([])


def test_live_report_persists(tmp_path):
    report = LiveBenchReport(model="llama", seconds=2.5)
    result = report_to_result(report)
    assert result.kind == "live" and result.duration_ms == 2500
    store = BenchStore(tmp_path)
    store.add(result)
    loaded = store.list(5)
    assert loaded[0].kind == "live" and loaded[0].model == "llama"
