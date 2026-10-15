"""RunPod REST API v2 adapter with explicit budget and destructive-action gates."""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class CloudGpuError(RuntimeError):
    """Cloud provider error safe to display in the desktop application."""


class RunPodClient:
    BASE_URL = "https://api.runpod.io/v2"

    def __init__(self, api_key: str, timeout_seconds: float = 30.0):
        self.api_key = str(api_key).strip()
        if not self.api_key:
            raise CloudGpuError("Enter and save a RunPod API key first.")
        if not 1 <= float(timeout_seconds) <= 180:
            raise CloudGpuError("Request timeout must be between 1 and 180 seconds.")
        self.timeout_seconds = float(timeout_seconds)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str | int] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/") or ".." in path.split("/"):
            raise CloudGpuError("Invalid provider endpoint.")
        url = self.BASE_URL + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(5 * 1024 * 1024 + 1)
                if len(raw) > 5 * 1024 * 1024:
                    raise CloudGpuError("Cloud API response exceeded 5 MiB.")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(2400).decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            detail = detail.replace(self.api_key, "[REDACTED]")[:900]
            raise CloudGpuError(f"RunPod returned HTTP {exc.code}. {detail}".strip()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudGpuError(f"Could not reach RunPod ({type(exc).__name__}).") from None
        if not raw:
            return {}
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise CloudGpuError("RunPod returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise CloudGpuError("RunPod returned an unexpected response.")
        return result

    def gpu_catalog(self, cloud: str = "SECURE") -> list[dict[str, Any]]:
        cloud = cloud.upper()
        if cloud not in {"SECURE", "COMMUNITY"}:
            raise CloudGpuError("Choose SECURE or COMMUNITY cloud.")
        response = self._request(
            "GET", "/catalog/gpus",
            query={"include": "AVAILABILITY", "product": "POD", "count": 1},
        )
        items = response.get("gpus")
        if not isinstance(items, list):
            raise CloudGpuError("RunPod GPU catalog did not contain a GPU list.")
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def gpu_hourly_price(gpu: dict[str, Any], cloud: str) -> float | None:
        """Read both REST v2 catalog price fields and compatible price maps."""
        cloud = cloud.lower()
        if cloud not in {"secure", "community"}:
            return None
        prices = gpu.get("price")
        value = prices.get(cloud) if isinstance(prices, dict) else None
        if value is None:
            value = gpu.get("securePrice" if cloud == "secure" else "communityPrice")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None

    def list_pods(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/pods")
        items = response.get("pods")
        if not isinstance(items, list):
            raise CloudGpuError("RunPod response did not contain a pod list.")
        return [item for item in items if isinstance(item, dict)]

    def plan_pod(
        self,
        *,
        gpu_id: str,
        max_gpu_hourly_usd: float,
        cloud: str = "SECURE",
        image: str = "runpod/pytorch:2.8.0-py3.11-cuda12.8.1",
        container_disk_gb: int = 30,
        name: str = "alterego-training",
    ) -> dict[str, Any]:
        cloud = cloud.upper()
        if cloud not in {"SECURE", "COMMUNITY"}:
            raise CloudGpuError("Choose SECURE or COMMUNITY cloud.")
        if not gpu_id or not gpu_id.strip():
            raise CloudGpuError("Choose a GPU from the current catalog.")
        if not math.isfinite(float(max_gpu_hourly_usd)) or max_gpu_hourly_usd <= 0:
            raise CloudGpuError("Hourly GPU budget must be positive.")
        if not 10 <= int(container_disk_gb) <= 1000:
            raise CloudGpuError("Container disk must be between 10 and 1000 GB.")
        if not image.strip() or len(image) > 300:
            raise CloudGpuError("Enter a valid container image.")
        if not name.strip() or len(name) > 100:
            raise CloudGpuError("Pod name must contain 1 to 100 characters.")

        matched = next(
            (item for item in self.gpu_catalog(cloud=cloud)
             if item.get("id") == gpu_id),
            None,
        )
        if matched is None:
            raise CloudGpuError("Selected GPU is no longer present in the live catalog.")
        price = self.gpu_hourly_price(matched, cloud)
        if price is None:
            raise CloudGpuError("GPU hourly rate was not supplied by the live catalog; refusing to create a pod.")
        if not math.isfinite(price) or price <= 0:
            raise CloudGpuError("GPU hourly rate is invalid; refusing to create a pod.")
        if price > float(max_gpu_hourly_usd):
            raise CloudGpuError(
                f"Live GPU price ${price:.4f}/hour exceeds your GPU-only limit "
                f"${float(max_gpu_hourly_usd):.4f}/hour."
            )
        return {
            "name": name,
            "gpu_id": gpu_id,
            "gpu_name": matched.get("name", matched.get("displayName", gpu_id)),
            "cloud": cloud,
            "image": image,
            "container_disk_gb": int(container_disk_gb),
            "gpu_hourly_usd": price,
            "availability": matched.get("availability"),
            "gpu_only_budget_usd": float(max_gpu_hourly_usd),
            "warning": (
                "The rate limit covers the listed GPU rate only and is not a total-bill cap. "
                "Container disk, storage, networking, and other account fees may apply. "
                "Terminating the pod may delete data stored only on its container disk."
            ),
        }

    def create_pod(self, plan: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise CloudGpuError("Provisioning is billable and disabled without explicit confirmation.")
        # Recheck live price immediately before provisioning.
        current = self.plan_pod(
            gpu_id=str(plan.get("gpu_id", "")),
            max_gpu_hourly_usd=float(plan.get("gpu_only_budget_usd", 0)),
            cloud=str(plan.get("cloud", "SECURE")),
            image=str(plan.get("image", "")),
            container_disk_gb=int(plan.get("container_disk_gb", 0)),
            name=str(plan.get("name", "alterego-training")),
        )
        payload = {
            "name": current["name"],
            "startSsh": True,
            "image": current["image"],
            "cloud": current["cloud"],
            "disk": current["container_disk_gb"],
            "gpu": {"id": current["gpu_id"], "count": 1},
        }
        command = str(plan.get("command") or "").strip()
        if command:
            # Официальный runpod-python (ctl_commands.create_pod, REST v2):
            # docker_args кладётся в поле "args". Поля "dockerArgs" в v2 нет.
            payload["args"] = command
        created = self._request("POST", "/pods", payload=payload)
        if not created.get("id"):
            raise CloudGpuError("RunPod did not return a pod ID.")
        # Подтверждаем, что под реально появился и не упал сразу; само
        # ВЫПОЛНЕНИЕ dockerArgs API не подтверждает — честно помечаем.
        pod_status = ""
        try:
            for pod in self.list_pods():
                if str(pod.get("id")) == str(created["id"]):
                    pod_status = str(pod.get("desiredStatus")
                                     or pod.get("status") or "")
                    break
        except Exception:
            pod_status = ""
        if pod_status.upper() in {"FAILED", "ERROR"}:
            raise CloudGpuError(
                f"RunPod создал под {created['id']}, но он сразу в статусе "
                f"{pod_status} — проверьте образ и dockerArgs.")
        return {**created,
                "confirmed_gpu_hourly_usd": current["gpu_hourly_usd"],
                "cost_warning": current["warning"],
                "pod_status": pod_status,
                "command_status": (
                    "команда отправлена полем args (RunPod REST v2, как в "
                    "официальном runpod-python); API не подтверждает запуск "
                    "команды внутри контейнера — проверьте логи/SSH пода")}

    # Конечные состояния RunPod (desiredStatus), подтверждающие действие.
    _FINAL_STATES = {"stop": {"EXITED", "STOPPED"},
                     "start": {"RUNNING"},
                     "terminate": {"TERMINATED"}}

    @staticmethod
    def pod_disk_summary(pod: dict[str, Any]) -> dict[str, Any]:
        """Диски пода из полей, которые реально вернул API (учёт при удалении)."""
        def num(*keys: str) -> float | None:
            for key in keys:
                value = pod.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
            return None

        return {
            "container_disk_gb": num("containerDiskInGb", "container_disk_gb",
                                     "diskInGb", "disk"),
            "volume_gb": num("volumeInGb", "persistentVolumeGb", "volume_gb"),
        }

    def verify_pod_state(self, pod_id: str, action: str, *,
                         attempts: int = 6, delay: float = 5.0,
                         sleep=time.sleep) -> dict[str, Any]:
        """STOP != TERMINATE: подтверждаем действие повторными опросами.

        stop: под остаётся, но desiredStatus EXITED; terminate: под ИСЧЕЗАЕТ
        из списка (или TERMINATED). Если опросить не удалось — честно
        confirmed=False, а не «наверное удалилось».
        """
        want = self._FINAL_STATES[action]
        last_status = ""
        last_error = ""
        for attempt in range(max(1, attempts)):
            if attempt:
                sleep(delay)
            try:
                pods = self.list_pods()
            except Exception as exc:
                last_error = str(exc)[:200]
                continue
            match = next((pod for pod in pods
                          if str(pod.get("id")) == str(pod_id)), None)
            if match is None:
                if action == "terminate":
                    return {"pod_id": pod_id, "action": action,
                            "confirmed": True, "final_status": "ABSENT",
                            "disk": {},
                            "note": ("Под исчез из списка: container disk "
                                     "удалён вместе с подом; сетевые тома "
                                     "(network volumes), если были, API не "
                                     "удаляет — проверьте тарификацию в "
                                     "консоли RunPod.")}
                last_status = "ABSENT"
                continue
            last_status = str(match.get("desiredStatus")
                              or match.get("status") or "")
            if last_status.upper() in want or (
                    action == "terminate"
                    and last_status.upper() == "TERMINATED"):
                return {"pod_id": pod_id, "action": action,
                        "confirmed": True, "final_status": last_status,
                        "disk": self.pod_disk_summary(match),
                        "note": ("Подтверждено опросом API: "
                                 f"{action} -> {last_status}")}
        return {"pod_id": pod_id, "action": action, "confirmed": False,
                "final_status": last_status or "UNKNOWN",
                "disk": {},
                "note": ("Конечное состояние НЕ подтверждено за отведённые "
                         f"опросы (последний статус: {last_status or '—'}"
                         + (f"; ошибка опроса: {last_error}" if last_error
                            else "")
                         + "). Проверьте под вручную в консоли RunPod.")}

    def pod_action(self, pod_id: str, action: str, *, confirmed: bool = False,
                   verify: bool = True, sleep=time.sleep) -> dict[str, Any]:
        if action not in {"start", "stop"}:
            raise CloudGpuError("Only start and stop actions are supported here.")
        if not confirmed:
            raise CloudGpuError(f"Pod {action} requires explicit confirmation.")
        pid = self._path_id(pod_id)
        result = self._request("POST", f"/pods/{pid}/action",
                               payload={"action": action})
        if verify:
            result = {**result,
                      "verification": self.verify_pod_state(
                          pod_id, action, sleep=sleep)}
        return result

    def terminate_pod(self, pod_id: str, *, confirmed: bool = False,
                      verify: bool = True, sleep=time.sleep) -> dict[str, Any]:
        if not confirmed:
            raise CloudGpuError("Pod termination is destructive and requires explicit confirmation.")
        pid = self._path_id(pod_id)
        disk_before: dict[str, Any] = {}
        try:
            for pod in self.list_pods():
                if str(pod.get("id")) == str(pod_id):
                    disk_before = self.pod_disk_summary(pod)
                    break
        except Exception:
            disk_before = {}
        result = self._request("DELETE", f"/pods/{pid}")
        if verify:
            result = {**result, "disk_before": disk_before,
                      "verification": self.verify_pod_state(
                          pod_id, "terminate", sleep=sleep)}
        return result

    @staticmethod
    def _path_id(pod_id: str) -> str:
        pod_id = str(pod_id).strip()
        if not pod_id or "/" in pod_id or ".." in pod_id or "\n" in pod_id:
            raise CloudGpuError("Invalid pod ID.")
        return urllib.parse.quote(pod_id, safe="")
