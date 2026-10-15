"""Pure path helpers for user-supplied file names inside the workspace."""
from __future__ import annotations

from pathlib import Path


class PathSafetyError(ValueError):
    """A user-supplied name is empty, unsafe, or escapes the root folder."""


def safe_child_path(root: str | Path, name: str) -> Path:
    """Resolve ``name`` (optionally with subfolders) safely inside ``root``.

    Rejects empty names, ``..`` components, absolute paths and NUL bytes.
    """
    value = str(name).strip().replace("\\", "/")
    if not value or "\x00" in value:
        raise PathSafetyError("Введите имя файла.")
    if value.startswith("/"):
        raise PathSafetyError("Укажите имя внутри рабочей папки, а не абсолютный путь.")
    parts = [part for part in value.split("/") if part]
    if not parts:
        raise PathSafetyError("Введите имя файла.")
    if any(part in {".", ".."} for part in parts):
        raise PathSafetyError("Имя не должно содержать '.' или '..'.")
    root_path = Path(root).expanduser().resolve()
    candidate = root_path.joinpath(*parts).resolve()
    if candidate != root_path and not candidate.is_relative_to(root_path):
        raise PathSafetyError("Путь выходит за пределы рабочей папки.")
    return candidate
