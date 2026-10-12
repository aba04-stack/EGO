"""Safe local Git operations for connecting model repositories."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class GitRepositoryError(RuntimeError):
    """A repository action failed or was refused safely."""


@dataclass(frozen=True)
class RepositoryStatus:
    path: str
    branch: str
    remote: str
    changes: tuple[str, ...]
    ahead_behind: str = ""


def validate_remote_url(url: str) -> str:
    """Accept credential-free HTTPS or standard SSH Git URLs only."""
    value = str(url).strip()
    if not value or any(ch.isspace() for ch in value):
        raise GitRepositoryError("Enter a valid repository URL.")
    if value.startswith("git@"):
        match = re.fullmatch(r"git@([A-Za-z0-9.-]+):([A-Za-z0-9_.\-/]+?)(?:\.git)?", value)
        if not match or ".." in match.group(2).split("/"):
            raise GitRepositoryError("SSH URL must use the form git@host:owner/repository.git.")
        return value

    try:
        parsed = urlsplit(value)
    except ValueError:
        raise GitRepositoryError("Repository URL is invalid.") from None
    if parsed.scheme != "https" or not parsed.hostname:
        raise GitRepositoryError("Use an HTTPS URL or a standard git@host SSH URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GitRepositoryError(
            "Repository URL must not contain credentials, query parameters, or fragments. "
            "Use your Git credential manager or GitHub CLI login instead."
        )
    segments = [segment for segment in parsed.path.strip("/").split("/") if segment]
    if len(segments) < 2 or any(segment in {".", ".."} for segment in segments):
        raise GitRepositoryError("URL must point to an owner/repository path.")
    return value


def repo_name_from_url(url: str) -> str:
    safe_url = validate_remote_url(url)
    if safe_url.startswith("git@"):
        path = safe_url.split(":", 1)[1]
    else:
        path = urlsplit(safe_url).path
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


class GitRepositoryManager:
    def __init__(self, timeout_seconds: float = 120.0):
        self.timeout_seconds = float(timeout_seconds)

    def _git(self, args: list[str], *, cwd: Path | None = None) -> str:
        command = ["git", *args]
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd) if cwd is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            raise GitRepositoryError(
                "Git was not found. Install Git for Windows and reopen the app."
            ) from None
        except subprocess.TimeoutExpired:
            raise GitRepositoryError("Git operation timed out; check your connection.") from None
        if result.returncode != 0:
            # Never echo URLs or credentials supplied by the user.
            message = result.stdout[-2500:].strip()
            # Credential-bearing URLs can exist in pre-existing local Git configs.
            message = re.sub(r"https?://[^/\s]+@", "https://[REDACTED]@", message)
            message = re.sub(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{10,}", "[REDACTED]", message)
            raise GitRepositoryError(message or f"git {' '.join(args[:2])} failed.")
        return result.stdout.strip()

    def connect_local(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_dir():
            raise GitRepositoryError(f"Folder does not exist: {candidate}")
        root = self._git(["rev-parse", "--show-toplevel"], cwd=candidate)
        repo = Path(root).resolve()
        if not (repo / ".git").exists():
            raise GitRepositoryError("Selected folder is not a Git repository.")
        return repo

    def clone(self, url: str, parent_dir: str | Path) -> Path:
        url = validate_remote_url(url)
        parent = Path(parent_dir).expanduser().resolve()
        if not parent.is_dir():
            raise GitRepositoryError("Choose an existing destination folder.")
        destination = parent / repo_name_from_url(url)
        if destination.exists():
            raise GitRepositoryError(
                f"Destination already exists: {destination}. Connect it locally instead."
            )
        self._git(["clone", "--", url, str(destination)], cwd=parent)
        return self.connect_local(destination)

    def current_branch(self, repo: str | Path) -> str:
        return self._git(["branch", "--show-current"], cwd=self.connect_local(repo))

    def list_branches(self, repo: str | Path) -> list[str]:
        output = self._git(["branch", "--format=%(refname:short)"], cwd=self.connect_local(repo))
        return sorted({line.strip() for line in output.splitlines() if line.strip()})

    def checkout_branch(self, repo: str | Path, branch: str) -> str:
        root = self.connect_local(repo)
        branch = str(branch).strip()
        if not branch or branch.startswith("-") or "\n" in branch or "\r" in branch:
            raise GitRepositoryError("Invalid branch name.")
        dirty = self._git(["status", "--porcelain"], cwd=root)
        if dirty:
            raise GitRepositoryError(
                "Repository has uncommitted changes. Commit or stash them before switching branches."
            )
        self._git(["checkout", branch], cwd=root)
        return self.current_branch(root)

    def refresh(self, repo: str | Path) -> str:
        root = self.connect_local(repo)
        self._git(["fetch", "--prune"], cwd=root)
        return self.status(root).branch

    def pull_fast_forward(self, repo: str | Path) -> str:
        root = self.connect_local(repo)
        self._git(["fetch", "--prune"], cwd=root)
        # FF-only deliberately refuses accidental merge commits or history rewrites.
        self._git(["pull", "--ff-only"], cwd=root)
        return self.status(root).branch

    def status(self, repo: str | Path) -> RepositoryStatus:
        root = self.connect_local(repo)
        branch = self._git(["branch", "--show-current"], cwd=root) or "(detached HEAD)"
        remote = self._git(["remote", "get-url", "origin"], cwd=root) if self._remote_exists(root) else ""
        # Display only a host/path, never credential-bearing URL components.
        if remote.startswith("git@"):
            remote_display = remote
        else:
            parsed = urlsplit(remote)
            remote_display = (
                f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
                if parsed.hostname else ("configured remote" if remote else "")
            )
        changes_text = self._git(["status", "--short"], cwd=root)
        changes = tuple(line for line in changes_text.splitlines() if line.strip())
        ahead_behind = ""
        try:
            ahead_behind = self._git(
                ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"], cwd=root
            )
        except GitRepositoryError:
            pass
        return RepositoryStatus(str(root), branch, remote_display, changes, ahead_behind)

    def _remote_exists(self, root: Path) -> bool:
        result = subprocess.run(
            ["git", "remote"],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        return result.returncode == 0 and "origin" in result.stdout.split()
