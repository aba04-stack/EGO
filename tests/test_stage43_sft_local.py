"""Этап 43: SFT-валидация, near-dup, деконтаминация, локальный инференс."""
from alterego_training_hub.local_inference import LocalServerManager, probe_all
from alterego_training_hub.sft_data import (
    decontaminate,
    dedupe_near,
    jaccard,
    near_duplicate_pairs,
    shingles,
    validate_sft,
)


def test_validate_messages_format():
    rows = [
        {"messages": [{"role": "user", "content": "Привет"},
                      {"role": "assistant", "content": "Здравствуйте"}]},
        {"messages": [{"role": "user", "content": "Вопрос без ответа"}]},
        {"messages": [{"role": "user", "content": ""},
                      {"role": "assistant", "content": "x"}]},
        {"instruction": "Сделай", "output": ""},
        {"prompt": "p", "completion": "c"},
        {"weird": 1},
    ]
    report = validate_sft(rows)
    assert not report.ok and report.problem_rows == 4
    assert report.formats["messages"] == 3
    assert any("не заканчивается assistant" in p for p in report.problems)


def test_shingles_and_jaccard():
    a = shingles("the quick brown fox jumps")
    b = shingles("the quick brown fox runs")
    assert 0 < jaccard(a, b) < 1


def test_near_dup_and_dedupe():
    rows = [
        {"text": "Обучение нейросети требует данных и времени"},
        {"text": "Обучение нейросети требует данных и времени!"},  # near dup
        {"text": "Совсем другой текст про кулинарию и рецепты"},
    ]
    pairs = near_duplicate_pairs(rows, threshold=0.6)
    assert pairs and pairs[0][0] == 0 and pairs[0][1] == 1
    _kept, removed = dedupe_near(rows, threshold=0.6)
    assert removed == 1 and len(_kept) == 2


def test_decontamination_removes_leakage():
    train = [{"text": "Столица Франции — Париж, город света"},
             {"text": "Рецепт борща со свёклой и сметаной"}]
    eval_rows = [{"text": "Столица Франции — Париж, город света!"}]
    result = decontaminate(train, eval_rows, threshold=0.6)
    assert result.contaminated == [0] and len(result.cleaned) == 1


def test_probe_with_fake_fetcher():
    def fetcher(url):
        if "11434" in url:
            return {"models": [{"name": "llama3"}]}
        raise ConnectionError("down")

    statuses = probe_all(fetcher=fetcher)
    assert statuses[0].up and statuses[0].models == ["llama3"]
    assert not statuses[1].up
    assert "работает" in statuses[0].render()


def test_local_manager_with_fake_runner():
    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            pass

    manager = LocalServerManager(runner=lambda argv: FakeProc())
    manager.available = lambda kind="ollama": True  # shutil may miss binary
    import alterego_training_hub.local_inference as li

    original = li.shutil.which
    li.shutil.which = lambda name: "/usr/bin/ollama"
    try:
        status = manager.start()
    finally:
        li.shutil.which = original
    assert status.up and manager.running
    assert manager.stop() and not manager.running


def test_messages_format_text_extraction():
    rows = [
        {"messages": [{"role": "user", "content": "Обучение нейросети требует данных"},
                      {"role": "assistant", "content": "Да, и времени"}]},
        {"messages": [{"role": "user", "content": "Обучение нейросети требует данных!"},
                      {"role": "assistant", "content": "Да, и времени!"}]},
    ]
    _kept, removed = dedupe_near(rows, threshold=0.5)
    assert removed == 1
    result = decontaminate(rows, [rows[0]], threshold=0.5)
    assert len(result.contaminated) == 2
