"""Total cloud budget guard (stage 44).

The hourly-rate gate prevents creating an expensive pod; this guard
answers the other question — *how much has the account already burned
in total?*  A JSON ledger in the app data dir records every observed
running pod (id, hourly rate, first/last seen).  Accrued spend is
summed over ledger entries; when a configured total cap is exceeded,
the guard stops the still-running pods (autostop).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import app_data_dir


@dataclass
class PodSpend:
    pod_id: str
    hourly_usd: float
    started_at: float
    stopped_at: float = 0.0  # 0 = still running (as far as we know)
    closed_usd: float = 0.0  # расходы прошлых сегментов (стоп→снова виден)
    managed: bool = False    # создан приложением: только такие автостопятся
    missing_syncs: int = 0   # подряд синхронизаций без этого пода

    def accrued(self, now: float) -> float:
        end = self.stopped_at or now
        hours = max(0.0, (end - self.started_at) / 3600.0)
        return self.closed_usd + hours * max(0.0, self.hourly_usd)


@dataclass
class BudgetLedger:
    path: Path = field(default_factory=lambda: app_data_dir() / "budget.json")
    pods: dict[str, PodSpend] = field(default_factory=dict)

    # ------------------------------------------------------------ persist
    @classmethod
    def load(cls, path: Path | None = None) -> BudgetLedger:
        ledger = cls(path=Path(path) if path else app_data_dir() / "budget.json")
        try:
            raw = json.loads(ledger.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ledger
        for item in raw.get("pods", []) if isinstance(raw, dict) else []:
            try:
                spend = PodSpend(**{k: item[k] for k in
                                    ("pod_id", "hourly_usd", "started_at",
                                     "stopped_at", "closed_usd", "managed",
                                     "missing_syncs") if k in item})
            except (TypeError, KeyError):
                continue
            ledger.pods[spend.pod_id] = spend
        return ledger

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pods": [vars(p) for p in self.pods.values()]}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)
        return self.path

    # ------------------------------------------------------------ tracking
    def observe(self, pod_id: str, hourly_usd: float,
                now: float | None = None, *, managed: bool = False) -> PodSpend:
        """Register/refresh a running pod.

        A pod that reappears after being marked stopped keeps its
        previously accrued spend: the closed segment is folded into
        ``closed_usd`` instead of being silently dropped.
        """
        now = time.time() if now is None else now
        spend = self.pods.get(pod_id)
        if spend is None:
            spend = PodSpend(pod_id=pod_id,
                             hourly_usd=float(hourly_usd or 0.0),
                             started_at=now)
            self.pods[pod_id] = spend
        elif spend.stopped_at:
            spend.closed_usd = spend.accrued(now)
            spend.started_at = now
            spend.stopped_at = 0.0
            if hourly_usd:
                spend.hourly_usd = float(hourly_usd)
        elif hourly_usd:
            spend.hourly_usd = float(hourly_usd)
        spend.missing_syncs = 0
        if managed:
            spend.managed = True
        return spend

    def mark_stopped(self, pod_id: str, now: float | None = None) -> None:
        spend = self.pods.get(pod_id)
        if spend is not None and not spend.stopped_at:
            spend.stopped_at = time.time() if now is None else now

    def total_spent(self, now: float | None = None) -> float:
        now = time.time() if now is None else now
        return sum(p.accrued(now) for p in self.pods.values())

    def running(self) -> list[PodSpend]:
        return [p for p in self.pods.values() if not p.stopped_at]


@dataclass
class BudgetVerdict:
    cap_usd: float
    spent_usd: float
    over: bool
    stopped: list[str] = field(default_factory=list)

    def render(self) -> str:
        if self.cap_usd <= 0:
            return f"Потолок не задан · потрачено ${self.spent_usd:.2f}"
        left = self.cap_usd - self.spent_usd
        base = (f"Бюджет: ${self.spent_usd:.2f} из ${self.cap_usd:.2f} "
                f"(осталось ${left:.2f}; локальная оценка с первого "
                "наблюдения пода, не финальный счёт провайдера)")
        if self.stopped:
            base += f" · АВТОСТОП: {', '.join(self.stopped)}"
        elif self.over:
            base += " · потолок превышен"
        return base


def check_budget(ledger: BudgetLedger, cap_usd: float,
                 stopper=None, now: float | None = None) -> BudgetVerdict:
    """Compute spend; when over cap, stop running pods via ``stopper``."""
    now = time.time() if now is None else now
    spent = ledger.total_spent(now)
    verdict = BudgetVerdict(cap_usd=float(cap_usd or 0.0),
                            spent_usd=spent,
                            over=bool(cap_usd and spent > cap_usd))
    if verdict.over and stopper is not None:
        # Автостоп — только поды, созданные приложением (managed):
        # чужие ресурсы аккаунта учитываем в расходах, но не трогаем.
        for spend in ledger.running():
            if not spend.managed:
                continue
            try:
                stopper(spend.pod_id)
            except Exception:
                continue
            ledger.mark_stopped(spend.pod_id, now)
            verdict.stopped.append(spend.pod_id)
    return verdict


ACTIVE_POD_STATUSES = {"RUNNING", "STARTING", "CREATED"}


def _pod_hourly(pod: dict) -> float:
    try:
        return float(pod.get("cost", pod.get("costPerHr", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def sync_ledger(ledger: BudgetLedger, pods, now: float | None = None) -> None:
    """Bring the ledger in line with the account's current pod list."""
    now = time.time() if now is None else now
    active_ids: set[str] = set()
    for pod in pods or []:
        pod_id = str((pod or {}).get("id") or "")
        if not pod_id:
            continue
        status = str(
            pod.get("desiredStatus") or pod.get("status") or "").upper()
        if status in ACTIVE_POD_STATUSES:
            ledger.observe(pod_id, _pod_hourly(pod), now=now)
            active_ids.add(pod_id)
        else:
            ledger.mark_stopped(pod_id, now=now)
    for spend in ledger.running():
        if spend.pod_id not in active_ids:
            # Один пропуск в ответе API — не доказательство остановки.
            spend.missing_syncs += 1
            if spend.missing_syncs >= 2:
                ledger.mark_stopped(spend.pod_id, now=now)


def apply_guard(ledger: BudgetLedger, pods, cap_usd: float,
                stopper=None, now: float | None = None) -> BudgetVerdict:
    """Sync ledger from pods, enforce cap, persist. Used by page+daemon."""
    sync_ledger(ledger, pods, now=now)
    verdict = check_budget(ledger, cap_usd,
                           stopper=stopper if cap_usd > 0 else None, now=now)
    ledger.save()
    return verdict
