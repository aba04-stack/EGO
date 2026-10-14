"""Cloud training job queue: RunPod/Colab-compatible submit & track flow.

Jobs live in a local JSON queue; submitting to RunPod goes through the
existing RunPodClient (injectable for tests). Nothing here talks to the
network until ``submit`` is called with a client.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

JOB_STATUSES = ("pending", "queued", "submitted", "running", "done",
                "failed", "cancelled")
ACTIVE_STATUSES = ("pending", "queued", "submitted", "running")


class CloudQueueError(RuntimeError):
    """Queue input error safe to display."""


@dataclass
class CloudJob:
    name: str
    command: str
    image: str = "runpod/pytorch:2.8.0-py3.11-cuda12.8.1"
    gpu_id: str = ""               # RunPod catalog gpu id (resolved on submit)
    max_gpu_hourly_usd: float = 0.0  # 0 = no explicit budget check here
    cloud: str = "SECURE"
    container_disk_gb: int = 30
    provider: str = "runpod"  # "runpod" | "colab" | "manual"
    status: str = "pending"
    pod_id: str = ""
    missing_polls: int = 0  # подряд ответов API без этого пода
    log: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def validate(self) -> None:
        if not self.name.strip() or len(self.name) > 120:
            raise CloudQueueError("Название задания: 1–120 символов.")
        if not self.command.strip():
            raise CloudQueueError("Команда задания не должна быть пустой.")
        if self.status not in JOB_STATUSES:
            raise CloudQueueError(f"Статус: один из {JOB_STATUSES}.")
        if self.provider not in {"runpod", "colab", "manual"}:
            raise CloudQueueError("Провайдер: runpod, colab или manual.")
        if self.cloud.upper() not in {"SECURE", "COMMUNITY"}:
            raise CloudQueueError("Облако: SECURE или COMMUNITY.")
        if not 10 <= int(self.container_disk_gb) <= 1000:
            raise CloudQueueError("Контейнерный диск: 10–1000 GB.")

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def line(self) -> str:
        marks = {"pending": "○", "queued": "…", "submitted": "→",
                 "running": "▶", "done": "✓", "failed": "✗",
                 "cancelled": "⊘"}
        return (f"{marks.get(self.status, '○')} [{self.status}] {self.name}"
                + (f" (pod {self.pod_id})" if self.pod_id else ""))


class CloudJobQueue:
    """CRUD over cloud_jobs.json plus submit/sync helpers."""

    def __init__(self, library_dir: Path):
        self.library_dir = Path(library_dir)
        self.path = self.library_dir / "cloud_jobs.json"

    def _load(self) -> list[CloudJob]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out: list[CloudJob] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                out.append(CloudJob(**{
                    key: value for key, value in item.items()
                    if key in CloudJob.__dataclass_fields__}))
            except TypeError:
                continue
        return out

    def _save(self, jobs: list[CloudJob]) -> Path:
        self.library_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([asdict(job) for job in jobs],
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        tmp.replace(self.path)  # атомарно: прерванная запись не портит очередь
        return self.path

    def add(self, job: CloudJob) -> CloudJob:
        job.validate()
        jobs = self._load()
        jobs.insert(0, job)
        self._save(jobs[:100])
        return job

    def list(self, limit: int = 30) -> list[CloudJob]:
        return self._load()[:max(1, int(limit))]

    def get(self, job_id: str) -> CloudJob:
        for job in self._load():
            if job.id == job_id:
                return job
        raise CloudQueueError(f"Задание не найдено: {job_id}")

    def update(self, job_id: str, **changes) -> CloudJob:
        jobs = self._load()
        for job in jobs:
            if job.id == job_id:
                for key, value in changes.items():
                    if key in CloudJob.__dataclass_fields__ and key != "id":
                        setattr(job, key, value)
                job.updated_at = time.time()
                job.validate()
                self._save(jobs)
                return job
        raise CloudQueueError(f"Задание не найдено: {job_id}")

    def cancel(self, job_id: str, client=None) -> CloudJob:
        """Cancel locally and, when a client is given, stop the cloud pod.

        Если завершить под НЕ удалось, задание НЕ помечается cancelled:
        расходы, скорее всего, продолжаются, и врать статусом нельзя.
        """
        job = self.get(job_id)
        if job.status in {"done", "failed", "cancelled"}:
            raise CloudQueueError(f"Задание уже завершено: {job.status}.")
        note = ""
        if client is not None and job.pod_id:
            try:
                client.terminate_pod(job.pod_id, confirmed=True)
                note = f"pod {job.pod_id} завершён в облаке"
            except Exception as exc:
                self.update(job_id, error=(
                    f"отмена не подтверждена: pod завершить не удалось "
                    f"({type(exc).__name__}: {exc})"))
                raise CloudQueueError(
                    f"Не удалось завершить pod {job.pod_id} в облаке: "
                    f"{type(exc).__name__}: {exc}. Задание НЕ отменено — "
                    "расходы могут продолжаться, завершите pod вручную "
                    "в консоли провайдера.") from None
        elif job.pod_id:
            note = ("⚠ клиент API недоступен: отменено только локально, "
                    "pod в облаке может продолжать работать и тарифицироваться")
        return self.update(job_id, status="cancelled",
                           log=(job.log + "\n" + note).strip())

    def next_pending(self) -> CloudJob | None:
        pending = [job for job in self._load() if job.status == "pending"]
        return pending[-1] if pending else None

    def submit(self, job_id: str, client, *, name_suffix: str = "alterego") \
            -> CloudJob:
        """Create a RunPod pod for the job and mark it submitted.

        The plan uses the exact shape ``RunPodClient.create_pod`` expects
        (gpu_id / budget / cloud / image / disk / name) so the client can
        re-check the live price before provisioning. Errors are recorded on
        the job; the queue stays usable.
        """
        job = self.get(job_id)
        if job.status not in {"pending", "queued"}:
            raise CloudQueueError(f"Задание не в очереди: {job.status}.")
        if job.provider == "colab":
            raise CloudQueueError(
                "Colab не автоматизирован API: экспортируйте задание "
                "в Colab (кнопка экспорта) и запустите ноутбук вручную.")
        if job.provider == "manual":
            return self.update(
                job_id, status="queued",
                log=("Ручной провайдер: выполните команду на своём сервере: "
                     f"{job.command}"))
        if client is None:
            raise CloudQueueError("Для RunPod нужен клиент API.")
        plan = {
            "name": f"{name_suffix}-{job.name}"[:60],
            "gpu_id": job.gpu_id,
            "gpu_only_budget_usd": float(job.max_gpu_hourly_usd),
            "cloud": job.cloud.upper(),
            "image": job.image,
            "container_disk_gb": int(job.container_disk_gb),
            "command": job.command,
        }
        try:
            pod = client.create_pod(plan, confirmed=True)
        except Exception as exc:
            return self.update(job_id, status="failed",
                               error=f"{type(exc).__name__}: {exc}")
        pod_id = str(pod.get("id") or pod.get("podId") or "")
        if pod_id:
            try:
                from .budget_guard import BudgetLedger

                ledger = BudgetLedger.load()
                ledger.observe(
                    pod_id,
                    float(pod.get("confirmed_gpu_hourly_usd")
                          or job.max_gpu_hourly_usd or 0),
                    managed=True)  # создан приложением — страж вправе стопорить
                ledger.save()
            except Exception:
                pass
        return self.update(
            job_id, status="submitted", pod_id=pod_id,
            log=(f"pod создан: {pod_id}; команда передана как dockerArgs — "
                 "убедитесь, что образ контейнера её исполняет "
                 "(иначе запустите обучение вручную по SSH)"))

    def sync(self, job_id: str, client) -> CloudJob:
        """Refresh job status from the provider (RunPod pod list)."""
        job = self.get(job_id)
        if not job.pod_id or job.status in {"done", "failed", "cancelled"}:
            return job
        try:
            pods = client.list_pods()
        except Exception as exc:
            return self.update(job_id, error=f"сбой опроса: {exc}")
        for pod in pods:
            if str(pod.get("id") or "") == job.pod_id:
                desired = str(pod.get("desiredStatus") or pod.get("status") or "")
                mapped = {"RUNNING": "running", "EXITED": "done",
                          "TERMINATED": "done", "FAILED": "failed"}.get(
                    desired.upper(), job.status)
                changes: dict = {"status": mapped, "missing_polls": 0}
                if mapped == "done" and job.status != "done":
                    # EXITED означает лишь «контейнер завершился»: обучение
                    # могло упасть внутри. Успех не выдумываем.
                    changes["log"] = (
                        job.log + "\n⚠ pod завершился (EXITED) — успешность "
                        "обучения НЕ подтверждена: проверьте логи и метрики "
                        "прогона перед использованием чекпоинтов").strip()
                return self.update(job_id, **changes)
        # Один пропуск ответа API — ещё не смерть пода (пагинация/лаг):
        # failed только после двух подряд пустых опросов.
        missing = int(job.missing_polls or 0) + 1
        if missing >= 2:
            return self.update(job_id, status="failed", missing_polls=missing,
                               error="pod не найден в облаке (2 опроса подряд)")
        return self.update(job_id, missing_polls=missing,
                           error="pod временно не виден в API (пропуск 1)")
