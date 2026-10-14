"""Persistent history of training runs with metric snapshots and scores."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import app_data_dir


@dataclass
class RunRecord:
    command: str
    workspace: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    log_path: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    returncode: int | None = None
    metrics_last: dict[str, float] = field(default_factory=dict)
    best: dict[str, float] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)
    analysis_score: float | None = None
    environment: dict = field(default_factory=dict)
    config_snapshot: dict = field(default_factory=dict)

    @property
    def running(self) -> bool:
        return self.ended_at is None

    @property
    def status_ru(self) -> str:
        if self.running:
            return "выполняется"
        if self.returncode == 0:
            return "успешно"
        return f"ошибка (код {self.returncode})"


class RunStore:
    """Keeps the most recent runs in a single JSON file."""

    MAX_RUNS = 50

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else (app_data_dir() / "runs.json")

    def _load(self) -> list[RunRecord]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict):
                records.append(RunRecord(**{
                    key: value for key, value in item.items()
                    if key in RunRecord.__dataclass_fields__
                }))
        return records

    def _save(self, records: list[RunRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([asdict(record) for record in records], ensure_ascii=False,
                       indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def start(self, command: str, workspace: str, log_path: str = "",
              environment: dict | None = None,
              config_snapshot: dict | None = None) -> RunRecord:
        record = RunRecord(command=command, workspace=workspace,
                           log_path=log_path,
                           environment=dict(environment or {}),
                           config_snapshot=dict(config_snapshot or {}))
        records = self._load()
        # Close any dangling "running" records — the process is gone by now.
        for old in records:
            if old.running:
                old.ended_at = time.time()
                old.returncode = old.returncode if old.returncode is not None else -1
        records.insert(0, record)
        self._save(records[: self.MAX_RUNS])
        return record

    def finish(self, record_id: str, returncode: int | None,
               metrics_last: dict[str, float] | None = None,
               best: dict[str, float] | None = None,
               anomalies: list[str] | None = None) -> RunRecord | None:
        records = self._load()
        for record in records:
            if record.id == record_id:
                record.ended_at = time.time()
                record.returncode = returncode
                if metrics_last:
                    record.metrics_last = dict(metrics_last)
                if best:
                    record.best = dict(best)
                if anomalies is not None:
                    record.anomalies = list(anomalies)
                self._save(records)
                return record
        return None

    def attach_score(self, record_id: str, score: float) -> None:
        records = self._load()
        for record in records:
            if record.id == record_id:
                record.analysis_score = float(score)
        self._save(records)

    def latest_running(self) -> RunRecord | None:
        for record in self._load():
            if record.running:
                return record
        return None

    def list(self, limit: int = 20) -> list[RunRecord]:
        return self._load()[: max(1, int(limit))]
