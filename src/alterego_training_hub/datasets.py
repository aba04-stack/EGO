"""Dataset library: catalogue training/eval data with stats and previews."""
from __future__ import annotations

import csv
import io
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DATASET_SUFFIXES = {".jsonl", ".json", ".csv", ".tsv", ".txt"}
SUPPORTED_FORMATS = {"jsonl", "json", "csv", "tsv", "txt"}
_IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}
MAX_PREVIEW_ROWS = 20
MAX_SCAN_FILES = 200


class DatasetError(RuntimeError):
    """Dataset input error safe to display."""


@dataclass
class DatasetEntry:
    name: str
    format: str = "jsonl"
    location: str = ""
    rows: int = 0
    size_bytes: int = 0
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    updated_at: float = field(default_factory=time.time)

    def validate(self) -> None:
        if not self.name.strip() or len(self.name) > 120:
            raise DatasetError("Название датасета: 1–120 символов.")
        if self.format not in SUPPORTED_FORMATS:
            raise DatasetError(f"Формат: один из {sorted(SUPPORTED_FORMATS)}.")
        if not self.location.strip() or len(self.location) > 500:
            raise DatasetError("Укажите путь или URI датасета.")
        self.updated_at = time.time()


def count_rows(path: Path, fmt: str) -> int:
    try:
        if fmt in {"jsonl", "txt"}:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                return sum(1 for line in handle if line.strip())
        if fmt in {"csv", "tsv"}:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                return max(0, sum(1 for _ in csv.reader(handle)) - 1)
        if fmt == "json":
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            return len(raw) if isinstance(raw, list) else 1
    except (OSError, json.JSONDecodeError):
        return 0
    return 0


def preview_rows(path: Path, fmt: str, limit: int = MAX_PREVIEW_ROWS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if fmt == "jsonl":
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        rows.append({"raw": line[:300]})
                    if len(rows) >= limit:
                        break
        elif fmt == "json":
            raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, list):
                rows = raw[:limit]
            else:
                rows = [raw]
        elif fmt in {"csv", "tsv"}:
            delimiter = "\t" if fmt == "tsv" else ","
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                reader = csv.DictReader(io.StringIO(handle.read(200_000)),
                                        delimiter=delimiter)
                for row in reader:
                    rows.append(dict(row))
                    if len(rows) >= limit:
                        break
        elif fmt == "txt":
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            rows = [{"text": line[:300]} for line in lines[:limit] if line.strip()]
    except (OSError, json.JSONDecodeError):
        return rows
    return rows


class DatasetLibrary:
    """CRUD over datasets.json inside the shared model-library folder."""

    def __init__(self, library_dir: Path):
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.library_dir / "datasets.json"

    def load(self) -> list[DatasetEntry]:
        if not self.manifest_path.exists():
            return []
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries = []
        for item in raw.get("datasets") if isinstance(raw, dict) else []:
            if isinstance(item, dict):
                entries.append(DatasetEntry(**{
                    key: value for key, value in item.items()
                    if key in DatasetEntry.__dataclass_fields__
                }))
        return entries

    def save(self, entries: list[DatasetEntry]) -> Path:
        payload = {"version": 1, "updated_at": time.time(),
                   "datasets": [asdict(entry) for entry in entries]}
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        tmp.replace(self.manifest_path)
        return self.manifest_path

    def add(self, entry: DatasetEntry) -> DatasetEntry:
        entry.validate()
        entries = self.load()
        entries.append(entry)
        self.save(entries)
        return entry

    def remove(self, entry_id: str) -> None:
        entries = self.load()
        remaining = [entry for entry in entries if entry.id != entry_id]
        if len(remaining) == len(entries):
            raise DatasetError("Датасет не найден в библиотеке.")
        self.save(remaining)

    def scan_folder(self, folder: str | Path, *, max_depth: int = 6) -> list[DatasetEntry]:
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise DatasetError(f"Папка не найдена: {root}")
        found: list[DatasetEntry] = []
        for path in sorted(root.rglob("*")):
            if len(found) >= MAX_SCAN_FILES:
                break
            if not path.is_file() or path.suffix.lower() not in DATASET_SUFFIXES:
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) > max_depth:
                continue
            if any(part in _IGNORED_DIRS for part in rel.parts):
                continue
            fmt = path.suffix.lower().lstrip(".")
            if fmt not in SUPPORTED_FORMATS:
                continue
            found.append(DatasetEntry(
                name=path.stem,
                format=fmt,
                location=str(rel),
                rows=count_rows(path, fmt),
                size_bytes=path.stat().st_size,
                notes=f"Найдено в {root.name}",
            ))
        return found
