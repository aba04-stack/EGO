"""Этап 41: LoRA/QLoRA параметры, воспроизводимость, экспорт прогонов."""
from alterego_training_hub.reproducibility import (
    collect_environment,
    pip_freeze,
    render_environment,
)
from alterego_training_hub.run_export import export_mlflow, to_csv
from alterego_training_hub.runs import RunRecord, RunStore
from alterego_training_hub.train_script import ScriptConfig, generate_script


def test_lora_params_render_into_script():
    cfg = ScriptConfig(path="lora", dataset_path="d.txt",
                       base_model="meta-llama/x", lora_r=8, lora_alpha=16,
                       qlora=True, grad_accum=4, seed=7,
                       target_modules="q_proj,v_proj")
    code = generate_script(cfg)
    assert '"r": 8' in code and '"qlora": true' in code
    assert "BitsAndBytesConfig" in code and "load_in_4bit=True" in code
    assert "gradient_accumulation_steps" in code
    assert 'seed=CONFIG["seed"]' in code
    compile(code, "train_llm.py", "exec")


def test_lora_validation():
    cfg = ScriptConfig(path="lora", dataset_path="d.txt",
                       base_model="m", lora_r=0)
    assert any("LoRA" in p for p in cfg.validate())


def test_environment_snapshot(tmp_path):
    env = collect_environment(tmp_path)
    assert env["python"] and env["packages"]
    assert any(p.startswith("pytest==") or "==" in p
               for p in env["packages"])
    assert render_environment(env)


def test_pip_freeze_sorted():
    rows = pip_freeze()
    assert rows == sorted(rows, key=str.lower)


def test_run_store_keeps_environment(tmp_path):
    store = RunStore(tmp_path / "runs.json")
    record = store.start("python train.py", str(tmp_path),
                         environment={"git_commit": "abc123"},
                         config_snapshot={"lr": 0.001})
    loaded = store.list(1)[0]
    assert loaded.id == record.id
    assert loaded.environment["git_commit"] == "abc123"
    assert loaded.config_snapshot["lr"] == 0.001


def test_exports(tmp_path):
    record = RunRecord(command="python train.py", workspace=str(tmp_path),
                       returncode=0, ended_at=10.0, started_at=5.0,
                       best={"val_loss": 1.5}, metrics_last={"loss": 2.0},
                       environment={"git_commit": "deadbeefcafe"})
    csv_text = to_csv([record])
    assert "best_val_loss" in csv_text and "deadbeefcafe" in csv_text
    mlruns = export_mlflow([record], tmp_path)
    run_dir = mlruns / "0" / record.id
    assert (run_dir / "meta.yaml").exists()
    assert "FINISHED" in (run_dir / "meta.yaml").read_text(encoding="utf-8")
    assert (run_dir / "metrics" / "best_val_loss").exists()
    assert (run_dir / "params" / "command").exists()
