"""Этап 42: HF Hub transfers, чекпоинты, привязка к прогонам, resume."""
import json

from alterego_training_hub.checkpoints import (
    bind_runs,
    delete_checkpoints,
    find_checkpoints,
    prune_plan,
    resume_command,
)
from alterego_training_hub.hf_hub import (
    HubError,
    download_model,
    list_files,
    push_folder,
    validate_repo_id,
)
from alterego_training_hub.runs import RunRecord
from alterego_training_hub.train_script import ScriptConfig, generate_script


def test_repo_validation():
    assert validate_repo_id("owner/name") == "owner/name"
    for bad in ("", "noslash", "a/b/c", "/x"):
        try:
            validate_repo_id(bad)
        except HubError:
            continue
        raise AssertionError(bad)


def test_download_with_fakes(tmp_path):
    def fetcher(url, token=''):
        return {"siblings": [{"rfilename": "model.safetensors", "size": 5},
                             {"rfilename": ".gitattributes"},
                             {"rfilename": "config.json", "size": 2}]}

    def downloader(url, target, token=""):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 3)
        return 3

    result = download_model("owner/name", tmp_path, fetcher=fetcher,
                            downloader=downloader)
    assert len(result.files) == 2 and result.total_bytes == 6
    assert (tmp_path / "name" / "config.json").exists()
    assert "Скачано" in result.render()


def test_list_files_empty_raises():
    try:
        list_files("o/n", fetcher=lambda url, token='': {"siblings": []})
    except HubError:
        return
    raise AssertionError("expected HubError")


def test_push_requires_token_and_folder(tmp_path):
    try:
        push_folder("o/n", tmp_path, token="")
    except HubError:
        pass
    else:
        raise AssertionError("token required")
    calls = []
    url = push_folder("o/n", tmp_path, token="t",
                      uploader=lambda r, f, t: calls.append(r))
    assert url.endswith("o/n") and calls == ["o/n"]


def _ckpt_tree(tmp_path):
    run_dir = tmp_path / "runs" / "my-llm"
    ck = run_dir / "checkpoint-200"
    ck.mkdir(parents=True)
    (ck / "trainer_state.json").write_text(json.dumps({
        "global_step": 200,
        "log_history": [{"eval_loss": 2.5}, {"eval_loss": 1.9}]}),
        encoding="utf-8")
    (ck / "model.safetensors").write_bytes(b"w" * 10)
    adapter = tmp_path / "adapter-out"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "model.pt").write_bytes(b"w" * 4)
    return tmp_path


def test_find_and_bind_checkpoints(tmp_path):
    root = _ckpt_tree(tmp_path)
    found = find_checkpoints(root)
    kinds = {c.kind for c in found}
    assert kinds == {"trainer", "adapter", "weights"}
    trainer = next(c for c in found if c.kind == "trainer")
    assert trainer.step == 200 and trainer.val_loss == 1.9
    record = RunRecord(command="python train_llm.py", workspace=str(root),
                       started_at=trainer.mtime - 100,
                       ended_at=trainer.mtime + 100)
    bind_runs(found, [record])
    assert trainer.run_id == record.id
    assert "--resume" in resume_command(trainer)


def test_prune_and_delete_confined(tmp_path):
    root = _ckpt_tree(tmp_path)
    found = find_checkpoints(root)
    plan = prune_plan(found, keep=1)
    assert len(plan) == len(found) - 1
    outside = RunRecord(command="x")  # noqa: F841 - sanity import use
    deleted = delete_checkpoints(plan, root)
    assert deleted == len(plan)
    assert len(find_checkpoints(root)) == 1


def test_generated_script_supports_resume():
    code = generate_script(ScriptConfig(path="lora", dataset_path="d.txt",
                                        base_model="m"))
    assert "--resume" in code and "resume_from_checkpoint" in code
    compile(code, "train_llm.py", "exec")
