"""Импорт run-record v2 (этап D): скрипт обучения → история приложения.

Сгенерированный `train_llm.py` пишет рядом с артефактами `run-record.json`
(schema 2): конфиг, версии библиотек, GPU, SHA-256 датасета, метрики и
контрольные суммы артефактов. Этот модуль валидирует запись и превращает
её в RunRecord истории; MLflow/CSV экспорт этапа 41 подхватывает её поля.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runs import RunRecord

SCHEMA = 2


def load_run_record(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("не run-record v2 (нет schema=2)")
    for key in ("status", "config", "dataset", "artifacts"):
        if key not in data:
            raise ValueError(f"run-record v2: нет поля {key}")
    return data


def to_run_record(data: dict[str, Any], source: Path) -> RunRecord:
    cfg = data.get("config") or {}
    dataset = data.get("dataset") or {}
    metrics = {k: float(v) for k, v in (data.get("metrics") or {}).items()
               if isinstance(v, (int, float))}
    environment = {
        "python": data.get("python", ""), "platform": data.get("platform", ""),
        "gpu": data.get("gpu", ""),
        **{f"lib_{k}": v for k, v in (data.get("versions") or {}).items()},
        "dataset_sha256": dataset.get("sha256", ""),
        "dataset_bytes": dataset.get("bytes", 0),
        "engine": data.get("engine", ""), "schema": SCHEMA,
    }
    return RunRecord(
        command=f"run-record v2 · {data.get('path', '')} "
                f"[{data.get('engine', '')}]",
        workspace=str(source.parent),
        log_path=str(source),
        started_at=float(data.get("started_at") or 0),
        ended_at=float(data.get("ended_at") or 0) or None,
        returncode=0 if data.get("status") == "success" else 1,
        metrics_last=metrics,
        best={"val_loss": metrics["eval_loss"]} if "eval_loss" in metrics
        else {},
        environment=environment,
        config_snapshot={k: v for k, v in cfg.items()
                         if isinstance(v, (str, int, float, bool))},
    )


def record_artifacts_ok(data: dict[str, Any], base: Path) -> list[str]:
    """Проверить контрольные суммы артефактов; вернуть список расхождений."""
    import hashlib

    broken = []
    for artifact in data.get("artifacts") or []:
        target = Path(base) / str(artifact.get("path", ""))
        if not target.is_file():
            broken.append(f"нет файла: {artifact.get('path')}")
            continue
        digest = hashlib.sha256()
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != artifact.get("sha256"):
            broken.append(f"sha256 не совпал: {artifact.get('path')}")
    return broken
