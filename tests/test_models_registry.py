import json

import pytest

from alterego_training_hub.models_registry import (
    ModelEntry,
    ModelRegistry,
    ModelRegistryError,
    validate_cloud_uri,
)


def test_crud_roundtrip(tmp_path):
    registry = ModelRegistry(tmp_path / "library")
    entry = ModelEntry(name="gpt-mini", kind="local", location="ckpt/model.safetensors",
                       metrics={"loss": 0.42})
    registry.add(entry)
    loaded = registry.load()
    assert len(loaded) == 1
    assert loaded[0].metrics["loss"] == 0.42

    entry.notes = "обучена"
    registry.update(entry)
    assert registry.get(entry.id).notes == "обучена"

    registry.remove(entry.id)
    assert registry.load() == []
    with pytest.raises(ModelRegistryError):
        registry.remove(entry.id)


def test_validation_rules():
    with pytest.raises(ModelRegistryError):
        ModelEntry(name="", location="x").validate()
    with pytest.raises(ModelRegistryError):
        ModelEntry(name="m", kind="cloud", location="ftp://x/y").validate()
    with pytest.raises(ModelRegistryError):
        ModelEntry(name="m", kind="local", location="x",
                   base_url="http://insecure.test/v1").validate()
    validate_cloud_uri("s3://bucket/models/gpt")
    validate_cloud_uri("hf://org/model")
    validate_cloud_uri("runpod://volume1/ckpt")


def test_scan_folder_finds_artifacts(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "model.safetensors").write_bytes(b"0" * 10)
    (tmp_path / "runs" / "adapter.gguf").write_bytes(b"1" * 10)
    (tmp_path / "runs" / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.bin").write_bytes(b"2" * 10)

    registry = ModelRegistry(tmp_path / "library")
    found = registry.scan_folder(tmp_path)
    names = {entry.name for entry in found}
    assert names == {"model", "adapter"}
    assert all(entry.kind == "local" for entry in found)


def test_export_import_manifest(tmp_path):
    registry = ModelRegistry(tmp_path / "library")
    registry.add(ModelEntry(name="a", kind="cloud", location="s3://b/a"))
    exported = registry.export_manifest(tmp_path / "backup")
    assert exported.exists()

    target = ModelRegistry(tmp_path / "other-library")
    count = target.import_manifest(exported)
    assert count == 1
    assert target.load()[0].name == "a"

    # merge keeps existing and adds only new ids
    target.add(ModelEntry(name="b", kind="local", location="b.gguf"))
    target.import_manifest(exported)
    names = {entry.name for entry in target.load()}
    assert names == {"a", "b"}

    with pytest.raises(ModelRegistryError):
        target.import_manifest(tmp_path / "missing.json")


def test_manifest_has_no_secret_fields(tmp_path):
    registry = ModelRegistry(tmp_path / "library")
    registry.add(ModelEntry(name="m", kind="cloud", location="https://models.example/m.safetensors",
                            base_url="https://api.example.test/v1"))
    raw = registry.manifest_path.read_text(encoding="utf-8").lower()
    assert "api_key" not in raw
    assert json.loads(raw)["models"][0]["kind"] == "cloud"
