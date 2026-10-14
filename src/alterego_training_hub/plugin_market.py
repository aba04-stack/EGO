"""Git plugin market (stage 46).

A market is any git repository with either:

* ``catalog.json`` — a list of entries like :mod:`plugin_catalog`
  (``source`` is a path relative to the repo root), or
* one folder per plugin containing ``plugin.py`` and an optional
  ``meta.json`` (``name``, ``version``, ``description``, ``author``).

Repos are cloned (later: ``git pull --ff-only``) into a cache under
the app data dir; installing copies the plugin file into the plugins
folder through the same checks as the built-in catalog (PLUGIN dict
required, optional sha256).  Git is invoked via an injectable runner
so tests stay offline.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import app_data_dir
from .plugin_catalog import CatalogEntry, CatalogError, install_entry


def market_cache_dir(url: str, base: Path | None = None) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    root = Path(base) if base else app_data_dir() / "market"
    return root / digest


def _git(runner, args: list[str], cwd: Path | None = None) -> None:
    try:
        completed = runner(["git", *args], cwd=cwd)
    except OSError as exc:
        raise CatalogError(f"git недоступен: {exc}") from exc
    if getattr(completed, "returncode", 0):
        raise CatalogError(
            f"git {' '.join(args[:2])} завершился с кодом "
            f"{completed.returncode}: "
            f"{str(getattr(completed, 'stderr', '') or '')[:200]}")


def _default_runner(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=180)


def sync_repo(url: str, base: Path | None = None,
              runner: Callable | None = None) -> Path:
    """Clone or fast-forward-update a market repo; returns its dir."""
    url = str(url or "").strip()
    if not url:
        raise CatalogError("Укажите URL git-репозитория маркета.")
    run = runner or _default_runner
    dest = market_cache_dir(url, base)
    if (dest / ".git").is_dir():
        _git(run, ["pull", "--ff-only"], cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(run, ["clone", "--depth", "1", url, str(dest)])
    return dest


def parse_market(repo_dir: Path) -> list[CatalogEntry]:
    """Catalog entries of a synced market repo (absolute file sources)."""
    repo_dir = Path(repo_dir)
    catalog_file = repo_dir / "catalog.json"
    entries: list[CatalogEntry] = []
    if catalog_file.is_file():
        try:
            raw = json.loads(catalog_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CatalogError(f"catalog.json маркета битый: {exc}") from exc
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", ""))
            path = (repo_dir / source).resolve()
            if not path.is_relative_to(repo_dir.resolve()):
                raise CatalogError(f"Источник вне репозитория: {source}")
            entry = CatalogEntry(
                id=str(item.get("id", "")), name=str(item.get("name", "")),
                version=str(item.get("version", "0")),
                description=str(item.get("description", "")),
                author=str(item.get("author", "")),
                source=f"file:{path}",
                sha256=str(item.get("sha256", "")))
            entry.id = entry.id or path.parent.name
            entry.name = entry.name or entry.id
            entries.append(entry)
        return entries
    for folder in sorted(repo_dir.iterdir()):
        plugin_file = folder / "plugin.py"
        if not folder.is_dir() or not plugin_file.is_file():
            continue
        meta: dict = {}
        meta_file = folder / "meta.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        entries.append(CatalogEntry(
            id=str(meta.get("id") or folder.name),
            name=str(meta.get("name") or folder.name),
            version=str(meta.get("version", "0")),
            description=str(meta.get("description", "")),
            author=str(meta.get("author", "")),
            source=f"file:{plugin_file}"))
    if not entries:
        raise CatalogError(
            "В репозитории не нашлось плагинов (нужен catalog.json "
            "или папки с plugin.py).")
    return entries


def load_market(url: str, base: Path | None = None,
                runner: Callable | None = None) -> list[CatalogEntry]:
    return parse_market(sync_repo(url, base=base, runner=runner))


def install_market_entry(entry: CatalogEntry, plugins_dir) -> Path:
    return install_entry(entry, plugins_dir)
