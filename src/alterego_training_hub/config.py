"""Per-user app settings and operating-system credential storage."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "AlterEgoTrainingHub"


def app_data_dir() -> Path:
    """Return a platform-appropriate user-private configuration directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    repo_path: str = ""
    workspace_path: str = ""
    mentor_provider: str = "OpenAI-compatible"
    mentor_base_url: str = ""
    mentor_model: str = ""
    mentor_temperature: float = 0.2
    mentor_max_tokens: int = 1200
    model_library_path: str = ""
    active_model_id: str = ""
    chat_autonomy: str = "assist"  # "assist" | "agent"
    ui_theme: str = "light"  # "light" | "dark"
    llm_provider: str = "openai"  # id from llm_providers.PROVIDERS
    agent_max_steps: int = 20
    agent_verify: bool = True
    agent_subagents: bool = True
    agent_reasoning: str = "medium"  # off | low | medium | high
    agent_system_extra: str = ""
    agent_profile: str = "full"  # preset id from agent_profiles
    gmail_from: str = ""
    training_command: str = "python -m pytest -q"
    runpod_cloud: str = "SECURE"
    runpod_max_gpu_hourly_usd: float = 0.50
    runpod_container_disk_gb: int = 30
    runpod_image: str = "runpod/pytorch:2.8.0-py3.11-cuda12.8.1"

    @classmethod
    def load(cls, path: Path | None = None) -> AppSettings:
        settings_path = path or (app_data_dir() / "settings.json")
        if not settings_path.exists():
            return cls()
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root must be an object")
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{key: value for key, value in raw.items() if key in allowed})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # Do not crash the whole UI due to a manually edited or partial config.
            return cls()

    def save(self, path: Path | None = None) -> Path:
        settings_path = path or (app_data_dir() / "settings.json")
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = settings_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(settings_path)
        return settings_path


class SecretStore:
    """Store credentials in the OS credential store using Python keyring.

    There is deliberately no plaintext-file fallback. On unsupported or locked
    systems, callers get an error they can show to the user.
    """

    def __init__(self, service: str = APP_NAME):
        self.service = service

    def get(self, name: str) -> str:
        try:
            import keyring
            value = keyring.get_password(self.service, name)
        except Exception as exc:
            raise RuntimeError(
                "The operating-system credential store is unavailable. "
                "Install/enable a supported keyring backend; no plaintext fallback is used."
            ) from exc
        return value or ""

    def set(self, name: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Credential value must not be empty.")
        try:
            import keyring
            keyring.set_password(self.service, name, value)
        except Exception as exc:
            raise RuntimeError(
                "Could not store the API key in the operating-system credential store."
            ) from exc

    def delete(self, name: str) -> None:
        try:
            import keyring
            keyring.delete_password(self.service, name)
        except Exception as exc:
            # A missing credential is equivalent to deletion success.
            if "not found" in str(exc).lower() or "password not found" in str(exc).lower():
                return
            raise RuntimeError(
                "Could not remove the credential from the operating-system credential store."
            ) from exc
