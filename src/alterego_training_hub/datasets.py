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


def read_rows(path: Path, fmt: str, limit: int = 0) -> list[dict[str, Any]]:
    """Read a whole dataset file into rows (optionally capped)."""
    rows = preview_rows(path, fmt, limit=limit if limit > 0 else 10**9)
    return rows


def write_rows(path: Path, rows: list[dict[str, Any]], fmt: str) -> Path:
    """Write rows to a dataset file in the given format (creates parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jsonl":
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    elif fmt == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    elif fmt in {"csv", "tsv"}:
        delimiter = "\t" if fmt == "tsv" else ","
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys, delimiter=delimiter,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    elif fmt == "txt":
        path.write_text("\n".join(str(row.get("text", "")) for row in rows) + "\n",
                        encoding="utf-8")
    else:
        raise DatasetError(f"Неподдерживаемый формат: {fmt}")
    return path


def split_rows(rows: list[dict[str, Any]], *, train: float = 0.8,
               val: float = 0.1, test: float = 0.1,
               seed: int = 42) -> dict[str, list[dict[str, Any]]]:
    """Deterministic shuffle + train/val/test split; ratios are normalised."""
    if not rows:
        return {"train": [], "val": [], "test": []}
    total = float(train) + float(val) + float(test)
    if total <= 0:
        raise DatasetError("Сумма долей разбиения должна быть больше нуля.")
    train_r, val_r = float(train) / total, float(val) / total
    order = list(range(len(rows)))
    import random

    random.Random(int(seed)).shuffle(order)
    n = len(order)
    n_train = max(1, round(n * train_r))
    n_val = round(n * val_r)
    if n_train + n_val > n:
        n_val = max(0, n - n_train)
    train_idx = order[:n_train]
    val_idx = order[n_train:n_train + n_val]
    test_idx = order[n_train + n_val:]
    return {"train": [rows[i] for i in train_idx],
            "val": [rows[i] for i in val_idx],
            "test": [rows[i] for i in test_idx]}


def filter_rows(rows: list[dict[str, Any]], *, field: str = "text",
                contains: str = "", excludes: str = "",
                min_chars: int = 0, max_chars: int = 0) -> list[dict[str, Any]]:
    """Filter rows by substring/length rules on one text field."""
    out: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get(field, "")) if isinstance(row, dict) else str(row)
        if contains and contains not in text:
            continue
        if excludes and excludes in text:
            continue
        if min_chars and len(text) < int(min_chars):
            continue
        if max_chars and len(text) > int(max_chars):
            continue
        out.append(row)
    return out


HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"
_MAX_HF_ROWS = 200
_MAX_HF_BYTES = 8_000_000


def fetch_hf_rows(repo_id: str, *, config: str = "default", split: str = "train",
                  limit: int = 50, token: str = "",
                  timeout: float = 30.0) -> list[dict[str, Any]]:
    """Download sample rows of a Hugging Face dataset via the public API.

    Network access is confined to ``datasets-server.huggingface.co``; the
    response is size-capped and parsed defensively.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    repo_id = str(repo_id or "").strip()
    if not repo_id or "/" not in repo_id or " " in repo_id or "?" in repo_id:
        raise DatasetError(
            "Идентификатор датасета должен быть вида «организация/имя».")
    limit = max(1, min(int(limit), _MAX_HF_ROWS))
    params = urllib.parse.urlencode({
        "dataset": repo_id, "config": config or "default",
        "split": split or "train", "offset": 0, "length": limit})
    url = f"{HF_DATASETS_SERVER}/rows?{params}"
    request = urllib.request.Request(url, headers={
        "User-Agent": "AlteregoTrainingHub/1.0"})
    if token:
        request.add_header("Authorization", f"Bearer {token.strip()}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(_MAX_HF_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise DatasetError(f"Hugging Face ответил ошибкой {exc.code}: "
                           f"{exc.reason}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise DatasetError(f"Не удалось подключиться к Hugging Face: {exc}") from None
    if len(payload) > _MAX_HF_BYTES:
        raise DatasetError("Ответ Hugging Face слишком большой.")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DatasetError("Некорректный ответ Hugging Face.") from None
    raw_rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(raw_rows, list):
        raise DatasetError("В ответе нет строк (проверьте имя датасета и split).")
    out: list[dict[str, Any]] = []
    for item in raw_rows:
        row = item.get("row") if isinstance(item, dict) else None
        if isinstance(row, dict):
            out.append(row)
    return out



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
