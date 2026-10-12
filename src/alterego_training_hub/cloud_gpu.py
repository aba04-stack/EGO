"""RunPod REST API v2 adapter with explicit budget and destructive-action gates."""
from __future__ import annotations

import json
import math
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
        created = self._request("POST", "/pods", payload=payload)
        if not created.get("id"):
            raise CloudGpuError("RunPod did not return a pod ID.")
        return {**created, "confirmed_gpu_hourly_usd": current["gpu_hourly_usd"],
                "cost_warning": current["warning"]}

    def pod_action(self, pod_id: str, action: str, *, confirmed: bool = False) -> dict[str, Any]:
        if action not in {"start", "stop"}:
            raise CloudGpuError("Only start and stop actions are supported here.")
        if not confirmed:
            raise CloudGpuError(f"Pod {action} requires explicit confirmation.")
        pid = self._path_id(pod_id)
        return self._request("POST", f"/pods/{pid}/action", payload={"action": action})

    def terminate_pod(self, pod_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise CloudGpuError("Pod termination is destructive and requires explicit confirmation.")
        pid = self._path_id(pod_id)
        return self._request("DELETE", f"/pods/{pid}")

    @staticmethod
    def _path_id(pod_id: str) -> str:
        pod_id = str(pod_id).strip()
        if not pod_id or "/" in pod_id or ".." in pod_id or "\n" in pod_id:
            raise CloudGpuError("Invalid pod ID.")
        return urllib.parse.quote(pod_id, safe="")
