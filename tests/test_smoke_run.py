"""Этап 32: smoke-прогон сгенерированного скрипта обучения."""
from alterego_training_hub.model_recipes import get_preset
from alterego_training_hub.smoke_run import smoke_script
from alterego_training_hub.train_script import ScriptConfig, generate_script


def _write(tmp_path, cfg: ScriptConfig):
    script = tmp_path / "train_llm.py"
    script.write_text(generate_script(cfg), encoding="utf-8")
    return script


def _cfg(tmp_path, **over) -> ScriptConfig:
    data = tmp_path / "data.txt"
    if not data.exists():
        data.write_text("строка данных для обучения модели\n" * 5,
                        encoding="utf-8")
    base = dict(path="scratch", preset=get_preset("llama-tiny"),
                dataset_path=str(data))
    base.update(over)
    return ScriptConfig(**base)


def test_smoke_generated_script_all_green(tmp_path):
    cfg = _cfg(tmp_path)
    report = smoke_script(_write(tmp_path, cfg), dataset_path=cfg.dataset_path)
    assert report.ok, report.render()
    assert "7/7" in report.render()
    assert report.passed == len(report.checks)


def test_smoke_missing_file_and_dataset(tmp_path):
    report = smoke_script(tmp_path / "nope.py")
    assert not report.ok and report.passed == 0
    cfg = _cfg(tmp_path)
    report2 = smoke_script(_write(tmp_path, cfg),
                           dataset_path=str(tmp_path / "gone.txt"))
    assert not report2.ok
    failed = [c.name for c in report2.checks if not c.ok]
    assert "загрузка датасета" in failed


def test_smoke_broken_script_fails_compile(tmp_path):
    script = tmp_path / "train_llm.py"
    script.write_text("def broken(:\n", encoding="utf-8")
    report = smoke_script(script)
    assert not report.ok
    assert report.checks[-1].name == "компиляция"
    assert not report.checks[-1].ok


def test_smoke_bad_config_flagged(tmp_path):
    cfg = _cfg(tmp_path, lr=0, epochs=0)
    report = smoke_script(_write(tmp_path, cfg), dataset_path=cfg.dataset_path)
    config_check = next(c for c in report.checks if c.name == "CONFIG скрипта")
    assert not config_check.ok and "lr" in config_check.detail
