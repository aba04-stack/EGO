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


def test_checkout_refuses_to_discard_dirty_work(tmp_path):
    repo = tmp_path / "model"
    _make_repo(repo)
    (repo / "README.md").write_text("modified\n", encoding="utf-8")
    with pytest.raises(GitRepositoryError, match="uncommitted"):
        GitRepositoryManager().checkout_branch(repo, "main")
