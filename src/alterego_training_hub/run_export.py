"""Export of run history (stage 41): CSV summary + MLflow file store.

``to_csv`` gives one row per run (command, status, best/last metrics,
mentor score, git commit).  ``export_mlflow`` writes a best-effort
MLflow file-store layout (``mlruns/0/<run_id>/…`` with params, metrics
and meta.yaml) that ``mlflow ui --backend-store-uri file:…`` can read,
so experiment history is not locked inside the app.
"""
from __future__ import annotations

import csv
import io
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .runs import RunRecord


def _row(record: RunRecord) -> dict[str, Any]:
    env = record.environment or {}
    return {
        "id": record.id,
        "started": time.strftime("%Y-%m-%d %H:%M:%S",
                                 time.localtime(record.started_at)),
        "status": record.status_ru,
        "command": record.command,
        "workspace": record.workspace,
        "returncode": record.returncode,
        "duration_s": (round(record.ended_at - record.started_at, 1)
                       if record.ended_at else ""),
        "best_val_loss": record.best.get("val_loss", ""),
        "last_loss": record.metrics_last.get("loss", ""),
        "score": record.analysis_score,
        "git_commit": str(env.get("git_commit", ""))[:12],
        "anomalies": "; ".join(record.anomalies),
    }


CSV_FIELDS = ["id", "started", "status", "command", "workspace",
              "returncode", "duration_s", "best_val_loss", "last_loss",
              "score", "git_commit", "anomalies"]


def to_csv(records: Iterable[RunRecord]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for record in records:
        writer.writerow(_row(record))
    return buffer.getvalue()


def _yaml_scalar(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'" if any(
        ch in text for ch in ":#'\"") else text


def export_mlflow(records: Iterable[RunRecord], out_dir: Path) -> Path:
    """Write an MLflow file-store tree; returns the ``mlruns`` path."""
    mlruns = Path(out_dir) / "mlruns"
    experiment = mlruns / "0"
    experiment.mkdir(parents=True, exist_ok=True)
    (experiment / "meta.yaml").write_text(
        "artifact_location: ./0\nexperiment_id: '0'\n"
        "lifecycle_stage: active\nname: Default\n", encoding="utf-8")
    for record in records:
        run_dir = experiment / record.id
        (run_dir / "params").mkdir(parents=True, exist_ok=True)
        (run_dir / "metrics").mkdir(parents=True, exist_ok=True)
        (run_dir / "tags").mkdir(parents=True, exist_ok=True)
        env = record.environment or {}
        params = {"command": record.command,
                  "workspace": record.workspace,
                  "git_commit": str(env.get("git_commit", "")),
                  "python": str(env.get("python", ""))}
        params.update({f"cfg_{k}": v
                       for k, v in (record.config_snapshot or {}).items()})
        for name, value in params.items():
            (run_dir / "params" / name).write_text(
                str(value)[:500], encoding="utf-8")
        stamp = int(record.started_at * 1000)
        for name, value in {**record.metrics_last,
                            **{f"best_{k}": v
                               for k, v in record.best.items()}}.items():
            (run_dir / "metrics" / name).write_text(
                f"{stamp} {value} 0\n", encoding="utf-8")
        status = "FINISHED" if record.returncode == 0 else "FAILED"
        (run_dir / "meta.yaml").write_text(
            f"end_time: {int((record.ended_at or record.started_at) * 1000)}\n"
            "entry_point_name: ''\n"
            f"experiment_id: '0'\n"
            "lifecycle_stage: active\n"
            f"name: {_yaml_scalar(record.command[:60])}\n"
            f"run_id: {record.id}\n"
            f"run_uuid: {record.id}\n"
            "source_name: ''\nsource_type: 4\nsource_version: ''\n"
            f"start_time: {stamp}\nstatus: {status}\n"
            "tags: []\nuser_id: alterego\n", encoding="utf-8")
    return mlruns
