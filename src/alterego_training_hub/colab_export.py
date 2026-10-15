"""Colab notebook export for cloud training jobs.

Turns a ``CloudJob`` into a ready-to-open ``.ipynb`` (nbformat 4, Colab
metadata) with cells: intro, environment setup, the training command and a
metrics tail helper. Notebooks are plain JSON — no notebook library needed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .cloud_queue import CloudJob, CloudJobQueue


class ColabExportError(RuntimeError):
    """Colab export input error safe to display."""


def _cell(cell_type: str, source: str) -> dict[str, Any]:
    lines = source.splitlines(keepends=True) or [""]
    if lines and lines[-1] and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    cell: dict[str, Any] = {
        "cell_type": cell_type,
        "metadata": {},
        "source": [*lines[:-1], lines[-1].rstrip("\n")],
    }
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    return cell


def notebook_for_job(job: CloudJob, *, intro: str = "") -> dict[str, Any]:
    """Build an nbformat-4 notebook dict replicating the job."""
    if not isinstance(job, CloudJob):
        raise ColabExportError("Для Colab нужно облачное задание.")
    title = job.name or job.id
    gpu = job.gpu_id or "по умолчанию"
    markdown = intro or (
        f"# {title}\n\n"
        f"Задание EGO ({job.id}).\n\n"
        f"* GPU: `{gpu}` · образ: `{job.image}` · диск: "
        f"{job.container_disk_gb} GB\n"
        f"* Статус при экспорте: **{job.status}**\n\n"
        "Ячейки ниже воспроизводят обучение. В Colab выберите GPU-рантайм "
        "(Среда выполнения → Сменить тип среды выполнения).")
    setup = (
        "# Среда: базовые зависимости и папка проекта\n"
        "import os, subprocess, sys\n"
        "%mkdir -p /content/alterego-run\n"
        "%cd /content/alterego-run\n"
        f"print('Образ при экспорте: {job.image}')\n"
        f"print('GPU при экспорте: {gpu}')")
    command = (
        "# Команда обучения из задания\n"
        f"!{job.command}")
    tail = (
        "# Хвост лога обучения\n"
        "import glob, os\n"
        "logs = sorted(glob.glob('/content/alterego-run/**/*.log', recursive=True))\n"
        "print('Логов:', len(logs))\n"
        "for path in logs[-1:]:\n"
        "    with open(path) as fh:\n"
        "        print('\\n'.join(fh.read().splitlines()[-40:]))")
    return {
        "cells": [
            _cell("markdown", markdown),
            _cell("code", setup),
            _cell("code", command),
            _cell("code", tail),
        ],
        "metadata": {
            "colab": {"provenance": False},
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def save_notebook(job: CloudJob, path: str | Path) -> Path:
    """Write the job notebook to ``path`` (parents created)."""
    notebook = notebook_for_job(job)
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(notebook, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return file


def default_notebook_name(job: CloudJob) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(job.created_at
                                                           or time.time()))
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-"
                   for ch in (job.name or job.id))[:40].strip("-") or "job"
    return f"colab-{safe}-{stamp}.ipynb"


def export_queue(queue: CloudJobQueue, out_dir: str | Path,
                 *, limit: int = 10) -> list[Path]:
    """Export the most recent queue jobs as notebooks."""
    directory = Path(out_dir)
    files: list[Path] = []
    for job in queue.list(limit=limit):
        files.append(save_notebook(job, directory / default_notebook_name(job)))
    return files
