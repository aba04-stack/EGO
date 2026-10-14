"""Model registry: local and cloud-hosted model artifacts with a JSON manifest.

The registry file (``models.json``) lives inside a user-chosen "model library"
folder. Point that folder at a cloud-synced directory (OneDrive, Google Drive,
Dropbox, Yandex.Disk, a mounted network share) to keep models catalogued
cloud-side; the manifest itself is portable via export/import.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .config import app_data_dir

MODEL_FILE_SUFFIXES = {".safetensors", ".gguf", ".bin", ".pt", ".ckpt", ".onnx", ".ggml"}
CLOUD_URI_SCHEMES = {"s3", "gs", "hf", "runpod", "https", "az", "azure", "webdav", "ssh"}

_IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}


class ModelRegistryError(RuntimeError):
    """Registry input error safe to display."""


@dataclass
class ModelEntry:
    name: str
    kind: str = "local"  # "local" | "cloud"
    location: str = ""   # relative path, absolute path, or cloud URI
    base_url: str = ""   # OpenAI-compatible inference endpoint (optional)
    model_id: str = ""   # API model id for the endpoint (optional)
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    updated_at: float = field(default_factory=time.time)

    def validate(self) -> None:
        if not self.name.strip() or len(self.name) > 120:
            raise ModelRegistryError("Название модели: 1–120 символов.")
        if self.kind not in {"local", "cloud"}:
            raise ModelRegistryError("Тип модели: local или cloud.")
        if not self.location.strip() or len(self.location) > 500:
            raise ModelRegistryError("Укажите путь или URI модели (до 500 символов).")
        if self.kind == "cloud":
            validate_cloud_uri(self.location)
        if self.base_url:
            parsed = urlsplit(self.base_url.strip())
            if parsed.scheme != "https" or not parsed.hostname:
                raise ModelRegistryError("URL инференса должен быть HTTPS.")
        for key, value in self.metrics.items():
            if not isinstance(key, str) or not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ModelRegistryError("Метрики должны быть числовыми.")
        self.updated_at = time.time()


def validate_cloud_uri(uri: str) -> str:
    value = str(uri).strip()
    if not value or any(ch.isspace() for ch in value):
        raise ModelRegistryError("URI облачного хранилища некорректен.")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in CLOUD_URI_SCHEMES or not (parsed.netloc or parsed.path):
        raise ModelRegistryError(
            "Поддерживаемые URI: s3://, gs://, hf://, runpod://, https://, az:// и т.п."
        )
    return value


def default_library_dir() -> Path:
    path = app_data_dir() / "model-library"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ModelRegistry:
    """CRUD over the models.json manifest inside a model-library folder."""

    def __init__(self, library_dir: Path | None = None):
        self.library_dir = Path(library_dir) if library_dir else default_library_dir()
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.library_dir / "models.json"

    # -- persistence -----------------------------------------------------
    def load(self) -> list[ModelEntry]:
        if not self.manifest_path.exists():
            return []
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries: list[ModelEntry] = []
        for item in raw.get("models") if isinstance(raw, dict) else []:
            if not isinstance(item, dict):
                continue
            try:
                entries.append(ModelEntry(**{
                    key: value for key, value in item.items()
                    if key in ModelEntry.__dataclass_fields__
                }))
            except TypeError:
                continue
        return entries

    def save(self, entries: list[ModelEntry]) -> Path:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": time.time(),
            "models": [asdict(entry) for entry in entries],
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.manifest_path)
        return self.manifest_path

    # -- CRUD ------------------------------------------------------------
    def add(self, entry: ModelEntry) -> ModelEntry:
        entry.validate()
        entries = self.load()
        entries.append(entry)
        self.save(entries)
        return entry

    def update(self, entry: ModelEntry) -> ModelEntry:
        entry.validate()
        entries = self.load()
        for index, existing in enumerate(entries):
            if existing.id == entry.id:
                entries[index] = entry
                self.save(entries)
                return entry
        raise ModelRegistryError("Модель не найдена в реестре.")

    def remove(self, entry_id: str) -> None:
        entries = self.load()
        remaining = [entry for entry in entries if entry.id != entry_id]
        if len(remaining) == len(entries):
            raise ModelRegistryError("Модель не найдена в реестре.")
        self.save(remaining)

    def get(self, entry_id: str) -> ModelEntry:
        for entry in self.load():
            if entry.id == entry_id:
                return entry
        raise ModelRegistryError("Модель не найдена в реестре.")

    # -- discovery -------------------------------------------------------
    def scan_folder(self, folder: str | Path, *, max_depth: int = 6) -> list[ModelEntry]:
        """Find model artifacts under a folder and build registry entries."""
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise ModelRegistryError(f"Папка не найдена: {root}")
        found: list[ModelEntry] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) > max_depth:
                continue
            if any(part in _IGNORED_DIRS for part in rel.parts):
                continue
            if path.suffix.lower() in MODEL_FILE_SUFFIXES:
                size_mb = path.stat().st_size / (1024 * 1024)
                found.append(ModelEntry(
                    name=path.stem,
                    kind="local",
                    location=str(rel),
                    notes=f"Найдено в {root.name}: {size_mb:.1f} MB",
                ))
        return found

    # -- portable manifest ----------------------------------------------
    def export_manifest(self, destination: str | Path) -> Path:
        dest = Path(destination).expanduser()
        if dest.is_dir():
            dest = dest / "models-manifest.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.manifest_path.read_text(encoding="utf-8")
                        if self.manifest_path.exists()
                        else json.dumps({"version": 1, "models": []}, indent=2),
                        encoding="utf-8")
        return dest

    def import_manifest(self, source: str | Path, *, merge: bool = True) -> int:
        src = Path(source).expanduser().resolve()
        if not src.is_file():
            raise ModelRegistryError(f"Файл манифеста не найден: {src}")
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
            items = raw.get("models") if isinstance(raw, dict) else []
        except (OSError, json.JSONDecodeError):
            raise ModelRegistryError("Манифест повреждён или не является JSON.") from None
        if not isinstance(items, list):
            raise ModelRegistryError("Манифест не содержит список моделей.")
        imported: list[ModelEntry] = []
        for item in items:
            if isinstance(item, dict):
                imported.append(ModelEntry(**{
                    key: value for key, value in item.items()
                    if key in ModelEntry.__dataclass_fields__
                }))
        if merge:
            existing = self.load()
            known_ids = {entry.id for entry in existing}
            existing.extend(entry for entry in imported if entry.id not in known_ids)
            self.save(existing)
            return len(imported)
        self.save(imported)
        return len(imported)
