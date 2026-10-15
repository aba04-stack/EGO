"""Hugging Face Hub transfers (stage 42).

Download a model's files into the local library and push a local
folder back to the Hub.  Network operations accept injectable
``fetcher``/``downloader``/``uploader`` callables so tests never touch
the network; the defaults use plain urllib (download) and the
optional ``huggingface_hub`` package (upload).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_ROOT = "https://huggingface.co/api/models/"
RESOLVE_ROOT = "https://huggingface.co/"
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
SKIP_FILES = {".gitattributes"}


class HubError(RuntimeError):
    """User-facing Hub failure."""


@dataclass
class HubFile:
    path: str
    size: int = 0


@dataclass
class DownloadResult:
    repo_id: str
    dest: Path
    files: list[str] = field(default_factory=list)
    total_bytes: int = 0

    def render(self) -> str:
        mb = self.total_bytes / 1e6
        return (f"Скачано {self.repo_id}: {len(self.files)} файлов, "
                f"{mb:.1f} МБ → {self.dest}")


def validate_repo_id(repo_id: str) -> str:
    repo = str(repo_id or "").strip()
    if not _REPO_RE.match(repo):
        raise HubError(f"Некорректный repo id: {repo_id!r}. "
                       "Ожидается формат owner/name.")
    return repo


def _fetch_json(url: str, token: str = "") -> Any:
    headers = {"Accept": "application/json",
               "User-Agent": "EGO-LLM-Studio"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def list_files(repo_id: str, token: str = "",
               fetcher: Callable | None = None) -> list[HubFile]:
    """Repository siblings via the Hub API."""
    repo = validate_repo_id(repo_id)
    fetch = fetcher or _fetch_json
    url = API_ROOT + urllib.parse.quote(repo, safe="/")
    try:
        data = fetch(url, token)
    except HubError:
        raise
    except Exception as exc:
        raise HubError(f"Не удалось получить список файлов {repo}: "
                       f"{type(exc).__name__}: {exc}") from exc
    files = []
    for sibling in (data or {}).get("siblings", []):
        name = sibling.get("rfilename", "")
        if name and name not in SKIP_FILES:
            files.append(HubFile(path=name, size=int(sibling.get("size") or 0)))
    if not files:
        raise HubError(f"В репозитории {repo} не нашлось файлов для скачивания.")
    return files


def _download_file(url: str, dest: Path, token: str = "") -> int:
    headers = {"User-Agent": "EGO-LLM-Studio"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=120) as response, \
            dest.open("wb") as handle:
        total = 0
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            handle.write(block)
            total += len(block)
    return total


def download_model(repo_id: str, dest_dir: Path, token: str = "",
                   fetcher: Callable | None = None,
                   downloader: Callable | None = None) -> DownloadResult:
    """Download all repo files into ``dest_dir/<repo-name>``."""
    repo = validate_repo_id(repo_id)
    files = list_files(repo, token, fetcher=fetcher)
    dest = Path(dest_dir) / repo.split("/")[-1]
    fetch_file = downloader or _download_file
    result = DownloadResult(repo_id=repo, dest=dest)
    for hub_file in files:
        url = (RESOLVE_ROOT + urllib.parse.quote(repo, safe="/")
               + "/resolve/main/" + urllib.parse.quote(hub_file.path))
        target = dest / hub_file.path
        try:
            size = fetch_file(url, target, token)
        except TypeError:
            size = fetch_file(url, target)
        result.files.append(str(target))
        result.total_bytes += int(size or hub_file.size or 0)
    return result


def push_folder(repo_id: str, folder: Path, token: str = "",
                uploader: Callable | None = None) -> str:
    """Upload a local folder to the Hub; returns the repo URL."""
    repo = validate_repo_id(repo_id)
    folder = Path(folder)
    if not folder.is_dir():
        raise HubError(f"Папка не найдена: {folder}")
    if not token:
        raise HubError("Для push нужен HF-токен (Коннекторы → Hugging Face).")
    if uploader is not None:
        uploader(repo, folder, token)
    else:
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:
            raise HubError(
                "Для push установите пакет: pip install huggingface_hub") from exc
        api = HfApi(token=token)
        api.create_repo(repo, exist_ok=True)
        api.upload_folder(repo_id=repo, folder_path=str(folder))
    return f"https://huggingface.co/{repo}"
