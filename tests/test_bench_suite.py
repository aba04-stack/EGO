"""Tests for benchmarks and batch prompt suites."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.bench import (
    BenchError,
    BenchResult,
    BenchStore,
    format_bench_table,
    parse_tokens,
    rank_benchmarks,
    run_benchmark,
)
from alterego_training_hub.prompt_suite import (
    PromptCase,
    SuiteError,
    default_suite,
    format_suite_report,
    load_suite,
    run_suite,
    save_suite,
)


class _Done:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_parse_tokens_and_run_benchmark():
    assert parse_tokens("warmup\ntokens=42 done") == 42
    assert parse_tokens("no markers") == 0

    calls = {"n": 0}

    def runner(argv):
        calls["n"] += 1
        return _Done(0, "tokens=100")

    result = run_benchmark("demo", "python infer.py", iterations=2, warmup=1,
                           runner=runner)
    assert result.ok() and result.iterations == 2
    assert calls["n"] == 3  # 1 warmup + 2 measured
    assert result.tokens_per_sec > 0

    result = run_benchmark("demo", "python infer.py", iterations=1, warmup=0,
                           runner=lambda argv: _Done(7, ""))
    assert not result.ok() and "7" in result.error

    with pytest.raises(BenchError):
        run_benchmark("demo", "   ")

    result = run_benchmark("demo", "python infer.py", iterations=1, warmup=0,
                           runner=lambda argv: (_ for _ in ()).throw(
                               FileNotFoundError()))
    assert not result.ok() and "не найдена" in result.error


def test_bench_store_and_ranking(tmp_path):
    store = BenchStore(tmp_path)
    first = BenchResult(model="big", command="run", iterations=3,
                        duration_ms=100, tokens_per_sec=50.0)
    second = BenchResult(model="small", command="run", iterations=3,
                         duration_ms=40, tokens_per_sec=80.0)
    store.add(first)
    store.add(second)
    loaded = store.list()
    assert [item.model for item in loaded] == ["small", "big"]
    assert json.loads(store.path.read_text(encoding="utf-8"))

    lines = rank_benchmarks(loaded)
    assert any("small" in line for line in lines)
    assert "Лучший результат: small" in lines[-1]
    table = format_bench_table(loaded)
    assert "Модель" in table and "small" in table
    assert rank_benchmarks([]) == ["Нет успешных замеров для сравнения."]
    assert "ошибка" in BenchResult(model="x", command="y",
                                   error="bad").line()


def test_default_suite_and_run_suite_grading():
    cases = default_suite()
    assert len(cases) >= 5
    for case in cases:
        case.validate()

    class FakeClient:
        model = "fake-1"

        def generate(self, prompt, *, system="", temperature=0.2,
                     max_tokens=400):
            output = "Градиентный спуск — метод оптимизации."
            if "17 * 24" in prompt:
                output = "ответ: 408"
            elif "Переведи" in prompt:
                output = "Training is successful."
            elif "столицу" in prompt:
                output = "Алматы"  # wrong on purpose
            latency = 120

            class R:
                pass

            r = R()
            r.output, r.latency_ms, r.error = output, latency, ""
            return r

    result = run_suite(FakeClient(), cases, max_tokens=200)
    assert result.total == len(cases)
    assert result.passed == len(cases) - 1  # Bishkek case fails expectation
    assert result.mean_latency_ms == 120
    report = format_suite_report(result)
    assert "Пройдено" in report and "не прошёл" in report

    class BrokenClient:
        model = "broken"

        def generate(self, prompt, **kwargs):
            raise RuntimeError("нет сети")

    result = run_suite(BrokenClient(), [PromptCase(prompt="привет")])
    assert result.passed == 0
    assert "ошибка" in format_suite_report(result)


def test_suite_save_and_load(tmp_path):
    cases = [PromptCase(prompt="вопрос", expect_contains="да", system="sys")]
    path = save_suite(tmp_path / "suite.json", cases)
    loaded = load_suite(path)
    assert loaded[0].prompt == "вопрос" and loaded[0].expect_contains == "да"

    with pytest.raises(SuiteError):
        load_suite(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(SuiteError):
        load_suite(bad)
    bad.write_text(json.dumps({"cases": [{"prompt": ""}]}), encoding="utf-8")
    with pytest.raises(SuiteError):
        load_suite(bad)
    with pytest.raises(SuiteError):
        run_suite(None, [])
