from pathlib import Path
import subprocess

import pytest

from alterego_training_hub.git_manager import (
    GitRepositoryError,
    GitRepositoryManager,
    repo_name_from_url,
    validate_remote_url,
)


@pytest.mark.parametrize("url", [
    "http://github.com/example/repo.git",
    "https://user:token@github.com/example/repo.git",
    "https://github.com/example/repo.git?token=secret",
    "https://github.com/",
    "not a url",
])
def test_rejects_unsafe_or_invalid_repository_urls(url):
    with pytest.raises(GitRepositoryError):
        validate_remote_url(url)


def test_accepts_https_and_ssh_urls():
    assert validate_remote_url("https://github.com/aba04-stack/AI.git")
    assert validate_remote_url("git@github.com:aba04-stack/AI.git")


def test_repo_name_comes_from_url():
    assert repo_name_from_url("https://github.com/example/my-model.git") == "my-model"
    assert repo_name_from_url("git@github.com:example/my-model.git") == "my-model"


def _make_repo(path: Path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "hub-test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Hub Test"], check=True)
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "initial"], check=True)


def test_connect_local_and_status(tmp_path):
    repo = tmp_path / "model"
    _make_repo(repo)
    manager = GitRepositoryManager()
    assert manager.connect_local(repo) == repo.resolve()
    status = manager.status(repo)
    assert status.path == str(repo.resolve())
    assert status.branch
    assert status.changes == ()



def test_git_error_redacts_credentials_from_remote_urls(monkeypatch, tmp_path):
    from types import SimpleNamespace

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=128,
            stdout="fatal: https://user:secret-token@github.com/owner/repo.git denied",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GitRepositoryError) as exc:
        GitRepositoryManager()._git(["fetch"], cwd=tmp_path)
    assert "secret-token" not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


def test_checkout_refuses_to_discard_dirty_work(tmp_path):
    repo = tmp_path / "model"
    _make_repo(repo)
    (repo / "README.md").write_text("modified\n", encoding="utf-8")
    with pytest.raises(GitRepositoryError, match="uncommitted"):
        GitRepositoryManager().checkout_branch(repo, "main")


def test_stage_unstage_commit_flow(tmp_path):
    repo = tmp_path / "model"
    _make_repo(repo)
    manager = GitRepositoryManager()
    (repo / "train.py").write_text("print('hi')\n", encoding="utf-8")

    manager.stage(repo, ["train.py"])
    status = manager.status(repo)
    assert any("train.py" in line for line in status.changes)
    assert "+print" in manager.diff_text(repo, staged=True)

    manager.unstage(repo, ["train.py"])
    status = manager.status(repo)
    assert any(line.startswith("??") and "train.py" in line
               for line in status.changes)

    manager.stage(repo, ["train.py"])
    manager.commit(repo, "add train script")
    status = manager.status(repo)
    assert status.changes == ()
    assert manager.numstat(repo) == ""
    assert manager.diff_text(repo, against_head=True) == ""


def test_discard_file_restores_tracked_and_deletes_untracked(tmp_path):
    repo = tmp_path / "model"
    _make_repo(repo)
    manager = GitRepositoryManager()
    (repo / "README.md").write_text("modified\n", encoding="utf-8")
    manager.discard_file(repo, "README.md")
    assert (repo / "README.md").read_text(encoding="utf-8") == "test\n"

    (repo / "scratch.txt").write_text("x", encoding="utf-8")
    manager.discard_file(repo, "scratch.txt")
    assert not (repo / "scratch.txt").exists()


def test_commit_and_stage_safety_checks(tmp_path):
    repo = tmp_path / "model"
    _make_repo(repo)
    manager = GitRepositoryManager()
    with pytest.raises(GitRepositoryError):
        manager.commit(repo, "   ")
    with pytest.raises(GitRepositoryError):
        manager.stage(repo, [])
    with pytest.raises(GitRepositoryError):
        manager.stage(repo, ["../outside.txt"])
    with pytest.raises(GitRepositoryError):
        manager.discard_file(repo, "missing.txt")
