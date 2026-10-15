import subprocess
import sys

import pytest

from alterego_training_hub.datasets import (
    DatasetEntry,
    DatasetError,
    DatasetLibrary,
    count_rows,
    preview_rows,
)
from alterego_training_hub.templates import (
    TemplateError,
    create_project,
    list_templates,
    load_config,
    save_config,
)


# ---------------------------------------------------------------- templates
def test_list_templates():
    templates = list_templates()
    ids = {item.id for item in templates}
    assert ids == {"minimal-lm", "sft-chat"}
    assert all(item.title and item.description for item in templates)


def test_scaffold_rejects_bad_input(tmp_path):
    with pytest.raises(TemplateError):
        create_project(tmp_path, "плохое имя")
    with pytest.raises(TemplateError):
        create_project(tmp_path / "missing", "proj")
    with pytest.raises(TemplateError):
        create_project(tmp_path, "proj", template_id="unknown")


def test_scaffolded_project_trains_and_logs_parseable_metrics(tmp_path):
    created = create_project(tmp_path, "demo", template_id="minimal-lm")
    assert set(created) == {"README.md", "config.json", "data/README.md",
                            "eval.py", "train.py"}
    project = tmp_path / "demo"

    result = subprocess.run(
        [sys.executable, str(project / "train.py")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0
    assert "loss=" in result.stdout
    assert "epoch 30/30" in result.stdout
    assert (project / "checkpoints" / "model.json").exists()

    # metrics must be parseable by the Hub's own parser
    from alterego_training_hub.metrics import parse_log
    summary = parse_log(result.stdout)
    assert summary.last.get("loss", 9) < 0.5
    assert summary.epoch_current == 30

    evaluation = subprocess.run(
        [sys.executable, str(project / "eval.py")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert evaluation.returncode == 0
    assert "val_loss=" in evaluation.stdout

    # duplicate name is refused
    with pytest.raises(TemplateError):
        create_project(tmp_path, "demo")


def test_sft_scaffold_runs(tmp_path):
    create_project(tmp_path, "sft", template_id="sft-chat")
    result = subprocess.run(
        [sys.executable, str(tmp_path / "sft" / "train.py")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 1  # empty dataset -> explicit refusal
    assert "train.jsonl" in result.stdout


def test_config_roundtrip(tmp_path):
    config = {"lr": 0.1, "epochs": 5, "batch_size": 8, "seed": 1}
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded["lr"] == 0.1
    with pytest.raises(TemplateError):
        save_config(tmp_path, {"lr": "fast"})
    with pytest.raises(TemplateError):
        load_config(tmp_path / "missing-dir-xyz")


# ----------------------------------------------------------------- datasets
def test_dataset_crud_and_validation(tmp_path):
    library = DatasetLibrary(tmp_path / "library")
    entry = DatasetEntry(name="dialogs", format="jsonl", location="data/train.jsonl",
                         rows=2, tags=["sft"])
    library.add(entry)
    assert library.load()[0].name == "dialogs"
    library.remove(entry.id)
    assert library.load() == []
    with pytest.raises(DatasetError):
        library.remove(entry.id)
    with pytest.raises(DatasetError):
        DatasetEntry(name="", format="jsonl", location="x").validate()
    with pytest.raises(DatasetError):
        DatasetEntry(name="x", format="parquet", location="x").validate()


def test_scan_counts_rows_and_preview(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "train.jsonl").write_text(
        '{"q": 1}\n{"q": 2}\n{"q": 3}\n', encoding="utf-8")
    (data / "notes.txt").write_text("a\nb\n", encoding="utf-8")
    (data / "table.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    (data / "skip.bin").write_bytes(b"\x00\x01")

    library = DatasetLibrary(tmp_path / "library")
    found = library.scan_folder(tmp_path)
    by_name = {entry.name: entry for entry in found}
    assert set(by_name) == {"train", "notes", "table"}
    assert by_name["train"].rows == 3
    assert by_name["notes"].rows == 2
    assert by_name["table"].rows == 2
    assert by_name["table"].format == "csv"

    rows = preview_rows(data / "train.jsonl", "jsonl", limit=2)
    assert rows == [{"q": 1}, {"q": 2}]
    csv_rows = preview_rows(data / "table.csv", "csv")
    assert csv_rows[0] == {"x": "1", "y": "2"}
    assert count_rows(data / "missing.jsonl", "jsonl") == 0
