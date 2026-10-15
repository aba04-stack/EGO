"""Reproducibility snapshot for a training run (stage 41).

Captures everything needed to repeat a run later: git commit and
dirty flag of the workspace, Python/platform, and the installed
package versions (the ``pip freeze`` equivalent, collected through
:mod:`importlib.metadata` — no subprocess, works inside the .exe).
Never raises: any missing piece is simply absent from the dict.
"""
from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_PACKAGES = 400


def pip_freeze() -> list[str]:
    """Installed distributions as ``name==version`` lines, sorted."""
    rows: list[str] = []
    try:
        distributions = importlib.metadata.distributions()
        for dist in distributions:
            name = dist.metadata.get("Name") or ""
            if name:
                rows.append(f"{name}=={dist.version}")
    except Exception:
        return []
    return sorted(rows, key=str.lower)[:MAX_PACKAGES]


def git_info(root: Path) -> dict[str, Any]:
    """Commit hash + dirty flag for ``root``; empty dict outside git."""
    def run(*args: str) -> str:
        try:
            out = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    commit = run("rev-parse", "HEAD")
    if not commit:
        return {}
    status = run("status", "--porcelain")
    return {"git_commit": commit,
            "git_dirty": bool(status),
            "git_branch": run("rev-parse", "--abbrev-ref", "HEAD")}


def collect_environment(root: Path | None = None) -> dict[str, Any]:
    """Full environment snapshot; safe to call anywhere, never raises."""
    env: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": pip_freeze(),
    }
    if root is not None:
        env.update(git_info(Path(root)))
    return env


def render_environment(env: dict[str, Any]) -> list[str]:
    """Short human-readable lines for reports/exports."""
    lines = []
    if env.get("git_commit"):
        dirty = " (есть незакоммиченные изменения)" if env.get("git_dirty") else ""
        lines.append(f"git: {env['git_commit'][:12]}"
                     f" · {env.get('git_branch', '?')}{dirty}")
    lines.append(f"python: {env.get('python', '?')} · {env.get('platform', '?')}")
    packages = env.get("packages") or []
    interesting = [p for p in packages
                   if p.split("==")[0].lower()
                   in {"torch", "transformers", "peft", "datasets",
                       "accelerate", "bitsandbytes", "trl"}]
    if interesting:
        lines.append("ключевые пакеты: " + ", ".join(interesting))
    lines.append(f"всего пакетов: {len(packages)}")
    return lines
