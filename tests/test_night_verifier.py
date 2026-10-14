"""Этап 38: верификатор ночного дежурства — деградация генераций и val_loss."""
from alterego_training_hub.night_watch import (
    WatchState,
    degradation_issues,
    load_state,
    save_state,
    state_from_tail,
)

TAIL_GOOD = """epoch 1/3
eval: val_loss=1.0
{"sample": {"step": 100, "prompt": "Привет", "text": "мир и свет вокруг нас", "checkpoint": "a"}}
"""
TAIL_BAD = """epoch 2/3
eval: val_loss=2.5
{"sample": {"step": 200, "prompt": "Привет", "text": "", "checkpoint": "b"}}
"""


def test_state_from_tail_and_roundtrip(tmp_path):
    state = state_from_tail(TAIL_GOOD)
    assert state.best_val_loss == 1.0
    assert state.samples and state.samples[-1]["text"].startswith("мир")
    path = save_state(tmp_path / "state.json", state)
    loaded = load_state(path)
    assert loaded.best_val_loss == 1.0
    assert loaded.samples == state.samples
    assert load_state(tmp_path / "missing.json").samples == []


def test_degradation_val_loss_and_empty_sample():
    issues = degradation_issues(state_from_tail(TAIL_GOOD),
                                state_from_tail(TAIL_BAD))
    joined = " ".join(issues)
    assert "Деградация" in joined and "val_loss" in joined
    assert "пуст" in joined


def test_degradation_repeated_sample_and_ok_case():
    prev = WatchState(samples=[{"text": "одинаковый текст генерации"}],
                      best_val_loss=1.0)
    cur = WatchState(samples=[{"text": "одинаковый текст генерации"}],
                     best_val_loss=1.05)
    issues = degradation_issues(prev, cur)
    assert any("повторяются дословно" in i for i in issues)
    better = WatchState(samples=[{"text": "новый хороший текст подлиннее"}],
                        best_val_loss=0.8)
    assert degradation_issues(prev, better) == []
    assert degradation_issues(WatchState(), cur) == []  # нет прошлого снимка
