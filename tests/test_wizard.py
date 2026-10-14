"""Этап 27: мастер «Своя ЛЛМ» — пресеты, аудит, калькулятор, токенизатор, план."""
from alterego_training_hub.data_audit import audit_rows
from alterego_training_hub.model_recipes import PRESETS, RECIPES, get_preset, recommend
from alterego_training_hub.resource_calc import (
    GPU_CATALOG,
    estimate,
    memory_need_gb,
    throughput_tps,
)
from alterego_training_hub.tokenizer_train import (
    ByteBPE,
    compression_stats,
    train_on_text,
)
from alterego_training_hub.wizard_plan import build_plan, compare_before_after


def test_presets_params_sane():
    small = get_preset("gpt2-small")
    assert 100_000_000 < small.params < 150_000_000
    assert "124M" in small.params_human or "125M" in small.params_human
    assert get_preset("nope").id == "gpt2-small"
    assert len(PRESETS) >= 5 and len(RECIPES) >= 5
    assert {r.path for r in RECIPES} == {"lora", "scratch", "recipe"}


def test_recommend_paths():
    lora = recommend(path="lora", params=7_000_000_000, data_tokens=50_000)
    assert lora.lr == 1e-4 and lora.epochs == 2  # мало данных
    scratch = recommend(path="scratch", params=100_000_000, data_tokens=500)
    assert any("Корпус" in n for n in scratch.notes)
    assert any("Ранняя остановка" in n for n in scratch.notes)


def test_audit_rows_flags():
    rows = [{"text": "Хорошая длинная строка данных"}] * 3 + [
        {"text": ""}, {"text": "пиши на mail@example.com или +7 999 111-22-33"}]
    audit = audit_rows(rows)
    assert audit.rows == 5 and audit.duplicates == 2 and audit.empty == 1
    assert audit.pii_hits == 1 and audit.score < 100
    assert any("PII" in line for line in audit.checklist())


def test_audit_clean_score_high():
    rows = [{"text": f"Уникальная строка номер {i} с достаточной длиной"}
            for i in range(150)]
    audit = audit_rows(rows)
    assert audit.duplicates == 0 and audit.pii_hits == 0 and audit.score >= 85


def test_memory_and_estimate():
    full = memory_need_gb(124_000_000, path="scratch")
    lora = memory_need_gb(7_000_000_000, path="lora")
    assert 1.0 < full < 12.0
    assert 14.0 < lora < 20.0  # 7B bf16 weights + adapter + activations
    est = estimate(params=124_000_000, data_tokens=1_000_000, epochs=3,
                   path="scratch")
    assert est.gpu is not None and est.hours > 0 and est.cost_usd > 0
    assert est.gpu.vram_gb >= est.need_gb
    huge = estimate(params=500_000_000_000, data_tokens=1000, path="scratch")
    assert huge.gpu is None
    assert GPU_CATALOG and throughput_tps(GPU_CATALOG[0], 7_000_000_000) > 0


def test_tokenizer_roundtrip(tmp_path):
    text = ("привет мир привет мир hello world hello " * 40)
    tok = train_on_text(text, vocab_size=300)
    ids = tok.encode("привет мир hello")
    assert ids and tok.decode(ids) == "привет мир hello"
    stats = compression_stats(tok, text)
    assert stats["tokens"] < stats["chars"]  # BPE сжимает повторы
    path = tok.save(tmp_path / "tok.json")
    loaded = ByteBPE.load(path)
    assert loaded.encode("hello world") == tok.encode("hello world")
    assert loaded.vocab_size == tok.vocab_size


def test_plan_render_contains_sections():
    rows = [{"text": f"Строка обучающих данных {i} подлиннее"} for i in range(120)]
    audit = audit_rows(rows)
    plan = build_plan(path="scratch", recipe_name="Обучить с нуля",
                      preset=get_preset("llama-tiny"), audit=audit)
    text = plan.render()
    for marker in ("🎯 Путь", "🧪 Аудит", "⚙ Рекомендации", "💰 Ресурсы", "▶ Шаги"):
        assert marker in text
    assert any("токенизатор" in s for s in plan.steps)


def test_before_after():
    result = compare_before_after(
        "epoch 1/3\neval: val_loss=2.0\n",
        "epoch 3/3\neval: val_loss=1.0\n")
    assert result.delta_pct == -50.0
    assert "улучшилась" in result.verdict
    empty = compare_before_after("", "")
    assert empty.before_best is None and "Нет данных" in empty.verdict
