"""Per-user app settings and operating-system credential storage."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import MISSING as _MISSING
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Keep this legacy storage/keyring ID stable across the EGO rebrand so existing
# settings and saved OS credentials remain available.
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
    embeddings_model: str = ""  # пусто = локальные hash-эмбеддинги в поиске
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
    access_role: str = "owner"  # owner | editor | viewer (guest, read-only)
    ui_language: str = "ru"  # ru | en (i18n)
    active_layout: str = "code"  # named layout from layouts.NAMED_LAYOUTS
    hotkeys: dict = field(default_factory=dict)  # action id -> bind sequence
    gmail_from: str = ""
    training_command: str = ""  # пусто = не задана (НЕ тесты!)
    runpod_cloud: str = "SECURE"
    runpod_max_gpu_hourly_usd: float = 0.50
    cloud_total_budget_usd: float = 0.0  # 0 = общий потолок выключен
    runpod_container_disk_gb: int = 30
    runpod_image: str = "runpod/pytorch:2.8.0-py3.11-cuda12.8.1"
    # Panel docking (drag-and-drop) and settings sync
    sidebar_side: str = "left"   # left | right
    sidebar_compact: bool = False  # activity-bar (иконки) вместо подписей
    update_repo: str = "aba04-stack/-"  # GitHub repo для проверки обновлений
    plugin_market_urls: list = field(default_factory=list)  # git-маркеты плагинов
    chat_side: str = "right"     # left | right
    bottom_height: int = 210     # px
    settings_sync_dir: str = ""
    synced_at: float = 0.0
    night_watch_enabled: bool = False
    night_watch_interval: int = 30  # minutes between night checks
    # Прозрачность ЛЛМ (этап 26)
    thought_protocol: bool = True   # структурный протокол «Мысль/Действие/Ответ»
    critic_enabled: bool = False    # самопроверка ответов («Критик»)

    # не поле dataclass: текст проблемы последней загрузки (для UI)
    load_error: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> AppSettings:
        settings_path = path or (app_data_dir() / "settings.json")
        if not settings_path.exists():
            return cls()
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root must be an object")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # Повреждённый файл НЕ проглатываем молча: сохраняем копию
            # рядом и честно сообщаем через load_error, что взяты умолчания.
            instance = cls()
            instance.load_error = (
                f"Файл настроек повреждён ({type(exc).__name__}); "
                "загружены значения по умолчанию")
            try:
                import time as _time
                backup = settings_path.with_name(
                    f"settings.json.corrupt-{int(_time.time())}")
                backup.write_bytes(settings_path.read_bytes())
                instance.load_error += f"; копия: {backup.name}"
            except OSError:
                pass
            return instance
        fields = cls.__dataclass_fields__
        values: dict = {}
        bad: list[str] = []
        for key, value in raw.items():
            if key not in fields or key == "load_error":
                continue
            field = fields[key]
            default = field.default
            if default is _MISSING and field.default_factory is not _MISSING:  # type: ignore[attr-defined]
                default = field.default_factory()  # type: ignore[misc]
            ok, coerced = _coerce_setting(default, value)
            if ok:
                values[key] = coerced
            else:
                bad.append(key)
        instance = cls(**values)
        if bad:
            instance.load_error = (
                "Некорректные типы в настройках (взяты умолчания): "
                + ", ".join(sorted(bad)))
        return instance

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


def _coerce_setting(default, value):
    """(ok, coerced) — привести значение из JSON к типу поля настроек."""
    if isinstance(default, bool):
        return (True, value) if isinstance(value, bool) else (False, None)
    if isinstance(default, int):
        if isinstance(value, bool):
            return False, None
        try:
            return True, int(value)
        except (TypeError, ValueError):
            return False, None
    if isinstance(default, float):
        if isinstance(value, bool):
            return False, None
        try:
            return True, float(value)
        except (TypeError, ValueError):
            return False, None
    if isinstance(default, str):
        return (True, value) if isinstance(value, str) else (False, None)
    if isinstance(default, list):
        if isinstance(value, list):
            return True, [str(item) for item in value]
        return False, None
    if isinstance(default, dict):
        return (True, value) if isinstance(value, dict) else (False, None)
    return True, value


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
