"""Checkpoint inventory (stage 42).

Finds training checkpoints inside a workspace: HF Trainer
``checkpoint-*`` folders (with ``trainer_state.json``), LoRA adapter
folders and plain ``*.pt`` dumps from the generated scratch script.
Each checkpoint can be bound to the run that produced it (same
workspace, run window covers the checkpoint mtime) and resumed.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .runs import RunRecord

MAX_DEPTH = 5
WEIGHT_SUFFIXES = {".safetensors", ".pt", ".bin"}


@dataclass
class Checkpoint:
    path: Path
    kind: str  # trainer | adapter | weights
    step: int = 0
    val_loss: float | None = None
    size_bytes: int = 0
    mtime: float = 0.0
    run_id: str = ""

    @property
    def name(self) -> str:
        return self.path.name

    def line(self) -> str:
        size = f"{self.size_bytes / 1e6:.0f} МБ"
        val = (f" · val_loss={self.val_loss:.3f}"
               if self.val_loss is not None else "")
        run = f" · прогон {self.run_id}" if self.run_id else ""
        return f"{self.name} [{self.kind}] · шаг {self.step or '—'}{val} · {size}{run}"


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _trainer_state(path: Path) -> tuple[int, float | None]:
    state_file = path / "trainer_state.json"
    if not state_file.exists():
        return 0, None
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, None
    step = int(state.get("global_step") or 0)
    val = None
    for entry in reversed(state.get("log_history", [])):
        if "eval_loss" in entry:
            val = float(entry["eval_loss"])
            break
    return step, val


def _classify(path: Path) -> Checkpoint | None:
    if path.is_dir():
        if path.name.startswith("checkpoint-"):
            step, val = _trainer_state(path)
            if not step:
                suffix = path.name.rsplit("-", 1)[-1]
                step = int(suffix) if suffix.isdigit() else 0
            return Checkpoint(path=path, kind="trainer", step=step,
                              val_loss=val, size_bytes=_dir_size(path),
                              mtime=path.stat().st_mtime)
        if (path / "adapter_config.json").exists():
            return Checkpoint(path=path, kind="adapter",
                              size_bytes=_dir_size(path),
                              mtime=path.stat().st_mtime)
        return None
    if path.suffix in WEIGHT_SUFFIXES and path.name != "optimizer.pt":
        return Checkpoint(path=path, kind="weights",
                          size_bytes=path.stat().st_size,
                          mtime=path.stat().st_mtime)
    return None


def find_checkpoints(root: Path, max_results: int = 100) -> list[Checkpoint]:
    """All checkpoints under ``root`` (bounded depth), newest first."""
    root = Path(root)
    found: list[Checkpoint] = []
    if not root.is_dir():
        return found
    for item in root.rglob("*"):
        rel = item.relative_to(root)
        if len(rel.parts) > MAX_DEPTH:
            continue
        if any(part in {".git", ".venv", "__pycache__"} for part in rel.parts):
            continue
        # A weight file inside a Trainer checkpoint or adapter directory is
        # part of that checkpoint, not a second independent checkpoint entry.
        if item.is_file():
            parents = [
                root.joinpath(*rel.parts[:index])
                for index in range(1, len(rel.parts))
            ]
            if any(
                parent.name.startswith("checkpoint-")
                or (parent / "adapter_config.json").is_file()
                for parent in parents
            ):
                continue
        checkpoint = _classify(item)
        if checkpoint is not None:
            found.append(checkpoint)
    found.sort(key=lambda c: c.mtime, reverse=True)
    return found[:max_results]


def bind_runs(checkpoints: list[Checkpoint],
              records: list[RunRecord]) -> list[Checkpoint]:
    """Attach the producing run id (workspace match + time window)."""
    for checkpoint in checkpoints:
        best: RunRecord | None = None
        for record in records:
            if not record.workspace:
                continue
            try:
                inside = checkpoint.path.is_relative_to(
                    Path(record.workspace))
            except (TypeError, ValueError):
                inside = False
            if not inside:
                continue
            end = record.ended_at or checkpoint.mtime
            if record.started_at - 5 <= checkpoint.mtime <= end + 3600:
                if best is None or record.started_at > best.started_at:
                    best = record
        checkpoint.run_id = best.id if best else ""
    return checkpoints


def resume_command(checkpoint: Checkpoint,
                   script: str = "train_llm.py") -> str:
    """Training command that resumes from this checkpoint."""
    return f"python {script} --resume {checkpoint.path}"


def prune_plan(checkpoints: list[Checkpoint],
               keep: int = 3) -> list[Checkpoint]:
    """Oldest checkpoints beyond ``keep`` newest (dry-run list)."""
    ordered = sorted(checkpoints, key=lambda c: c.mtime, reverse=True)
    return ordered[max(1, keep):]


def delete_checkpoints(checkpoints: list[Checkpoint], root: Path) -> int:
    """Delete checkpoint dirs/files, confined to ``root``; returns count."""
    root = Path(root).resolve()
    deleted = 0
    for checkpoint in checkpoints:
        path = checkpoint.path.resolve()
        if not path.is_relative_to(root):
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            deleted += 1
        except OSError:
            continue
    return deleted
