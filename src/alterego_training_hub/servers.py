"""Remote servers over SSH: registry, connection checks, command execution.

Connection settings live in a JSON file under the app data directory; secrets
(passwords / key passphrases) go to the OS credential store only. The SSH
transport is paramiko, imported lazily so the rest of the app works without it.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import SecretStore, app_data_dir

DEFAULT_PORT = 22
DEFAULT_TIMEOUT = 60.0
_CONNECT_TIMEOUT = 15.0
_MAX_OUTPUT = 200_000


def known_hosts_path() -> Path:
    """App-managed known_hosts: host keys are pinned on first use (TOFU)."""
    return app_data_dir() / "known_hosts"

INFO_COMMAND = (
    "uname -srmo; hostname; echo '---GPU---'; "
    "nvidia-smi --query-gpu=name,memory.total,utilization.gpu --format=csv,noheader "
    "2>/dev/null || echo 'GPU: не найдена'; echo '---DISK---'; "
    "df -h / | tail -1; echo '---LOAD---'; uptime"
)


class ServerError(RuntimeError):
    """User-facing error for server operations."""


class Runner(Protocol):
    def connect(self) -> None: ...
    def run(self, command: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]: ...
    def close(self) -> None: ...


@dataclass
class ServerEntry:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = ""
    host: str = ""
    port: int = DEFAULT_PORT
    user: str = ""
    auth_kind: str = "key"  # "key" (agent or key file) | "password"
    key_path: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ServerError("Укажите имя сервера.")
        if not self.host.strip():
            raise ServerError("Укажите хост (IP или домен).")
        if not self.user.strip():
            raise ServerError("Укажите SSH-пользователя.")
        try:
            port = int(self.port)
        except (TypeError, ValueError):
            raise ServerError("Порт должен быть числом.") from None
        if not 1 <= port <= 65535:
            raise ServerError("Порт должен быть в диапазоне 1..65535.")
        self.port = port
        if self.auth_kind not in {"key", "password"}:
            raise ServerError("Авторизация: «key» (ключ/агент) или «password».")
        self.name = self.name.strip()
        self.host = self.host.strip()
        self.user = self.user.strip()
        self.key_path = (self.key_path or "").strip()

    @property
    def address(self) -> str:
        return f"{self.user}@{self.host}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ServerEntry:
        entry = cls()
        entry.id = str(raw.get("id") or entry.id)
        entry.name = str(raw.get("name") or "")
        entry.host = str(raw.get("host") or "")
        try:
            entry.port = int(raw.get("port") or DEFAULT_PORT)
        except (TypeError, ValueError):
            entry.port = DEFAULT_PORT
        entry.user = str(raw.get("user") or "")
        entry.auth_kind = str(raw.get("auth_kind") or "key")
        entry.key_path = str(raw.get("key_path") or "")
        return entry


class ServerStore:
    """JSON-file registry of server entries (no secrets inside)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else (app_data_dir() / "servers.json")

    def list(self) -> list[ServerEntry]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        return [ServerEntry.from_dict(item) for item in raw
                if isinstance(item, dict)]

    def get(self, server_id: str) -> ServerEntry | None:
        return next((entry for entry in self.list() if entry.id == server_id), None)

    def find(self, ref: str) -> ServerEntry | None:
        """Resolve by id or by name."""
        ref = str(ref or "").strip()
        return next((entry for entry in self.list()
                     if entry.id == ref or entry.name == ref), None)

    def save(self, entry: ServerEntry) -> ServerEntry:
        entry.validate()
        entries = self.list()
        entries = [item for item in entries if item.id != entry.id]
        entries.append(entry)
        self._write(entries)
        return entry

    def delete(self, server_id: str) -> None:
        entries = [item for item in self.list() if item.id != server_id]
        self._write(entries)

    def _write(self, entries: list[ServerEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([entry.to_dict() for entry in entries],
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_OUTPUT else text[:_MAX_OUTPUT] + "\n…[обрезано]"


class SshRunner:
    """One SSH connection backed by paramiko (imported on connect).

    Host keys are verified against the system known_hosts plus an app-managed
    file: unknown keys are pinned on first use (trust-on-first-use, like
    ``ssh -o StrictHostKeyChecking=accept-new``) and rejected silently later if
    they change. The remote host-key fingerprint is exposed for the UI.
    """

    def __init__(self, host: str, port: int, user: str, *,
                 password: str = "", key_path: str = "",
                 connect_timeout: float = _CONNECT_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.key_path = key_path
        self.connect_timeout = float(connect_timeout)
        self._client: Any = None
        self.host_fingerprint = ""

    def connect(self) -> None:
        try:
            import paramiko
        except ImportError as exc:
            raise ServerError(
                "SSH-библиотека paramiko не установлена. "
                "Выполните: pip install paramiko"
            ) from exc
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        pin_file = known_hosts_path()
        if pin_file.exists():
            try:
                client.load_host_keys(str(pin_file))
            except Exception as exc:
                # Повреждённый файл пинов нельзя игнорировать: иначе
                # изменившийся ключ молча запинится как новый.
                raise ServerError(
                    "SSH: не удалось прочитать known_hosts приложения "
                    f"({pin_file}): {exc}. Исправьте или удалите файл."
                ) from None

        pin_errors: list[OSError] = []

        class PinOnFirstUse(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, ssh_client, hostname, key):
                ssh_client.get_host_keys().add(hostname, key.get_name(), key)
                try:
                    pin_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(pin_file, "a", encoding="utf-8") as handle:
                        handle.write(
                            f"{hostname} {key.get_name()} {key.get_base64()}\n")
                except OSError as exc:
                    # Fail-closed: без сохранённого пина следующее
                    # подключение приняло бы ключ вслепую. Соединение
                    # будет прервано сразу после connect (см. ниже).
                    pin_errors.append(exc)

        client.set_missing_host_key_policy(PinOnFirstUse())
        connect_kwargs: dict[str, Any] = {
            "hostname": self.host,
            "port": self.port,
            "username": self.user,
            "timeout": self.connect_timeout,
            "banner_timeout": self.connect_timeout,
            "auth_timeout": self.connect_timeout,
        }
        if self.password:
            connect_kwargs["password"] = self.password
        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        try:
            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException:
            raise ServerError("SSH: отказ в авторизации (проверьте пользователя, "
                              "ключ или пароль).") from None
        except paramiko.BadHostKeyException as exc:
            raise ServerError(
                "SSH: ключ сервера изменился (возможна атака). Проверьте "
                f"known_hosts: {exc}.") from None
        except (paramiko.SSHException, OSError, TimeoutError) as exc:
            raise ServerError(f"SSH: не удалось подключиться ({exc}).") from None
        if pin_errors:
            try:
                client.close()
            except Exception:
                pass
            raise ServerError(
                "SSH: не удалось сохранить ключ сервера в known_hosts "
                f"({pin_file}): {pin_errors[0]}. Подключение прервано: "
                "без пина проверка доверия не работала бы.")
        self._client = client
        try:
            import base64
            import hashlib

            remote_key = client.get_transport().get_remote_server_key()
            digest = hashlib.sha256(remote_key.asbytes()).digest()
            self.host_fingerprint = ("SHA256:"
                                     + base64.b64encode(digest).decode()
                                     .rstrip("="))
        except Exception:
            self.host_fingerprint = ""

    def run(self, command: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        if self._client is None:
            raise ServerError("SSH-сессия не открыта.")
        try:
            _stdin, stdout, stderr = self._client.exec_command(
                command, timeout=float(timeout))
            # stdout и stderr читаем ПАРАЛЛЕЛЬНО: последовательное чтение
            # упирается в окно SSH-канала и вешает команду с большим
            # выводом. Сверх лимита продолжаем читать и выбрасывать,
            # чтобы удалённый процесс не блокировался на записи.
            import threading as _threading

            chunks: dict[str, list[bytes]] = {"out": [], "err": []}
            sizes = {"out": 0, "err": 0}

            def drain(stream, slot):
                while True:
                    data = stream.read(32768) if hasattr(stream, "read") \
                        else b""
                    if not data:
                        break
                    if sizes[slot] <= _MAX_OUTPUT:
                        keep = data[:_MAX_OUTPUT + 1 - sizes[slot]]
                        chunks[slot].append(keep)
                        sizes[slot] += len(keep)

            threads = [
                _threading.Thread(target=drain, args=(stdout, "out"),
                                  daemon=True),
                _threading.Thread(target=drain, args=(stderr, "err"),
                                  daemon=True),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=float(timeout) + 5)
            if any(thread.is_alive() for thread in threads):
                try:
                    stdout.channel.close()
                except Exception:
                    pass
                raise ServerError(
                    "SSH: команда превысила тайм-аут чтения вывода.")
            exit_code = stdout.channel.recv_exit_status()
            raw_out = b"".join(chunks["out"])
            raw_err = b"".join(chunks["err"])
        except (OSError, TimeoutError) as exc:
            raise ServerError(f"SSH: команда не выполнена ({exc}).") from None
        except Exception as exc:  # paramiko transport errors
            raise ServerError(f"SSH: ошибка сессии ({exc}).") from None
        output = raw_out.decode("utf-8", errors="replace")
        err = raw_err.decode("utf-8", errors="replace")
        text = output + (("\n" + err) if err.strip() else "")
        return {"ok": exit_code == 0, "exit_code": exit_code,
                "command": command, "output": _clip(text)}

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


def default_runner_factory(entry: ServerEntry, secret: str) -> Runner:
    password = secret if entry.auth_kind == "password" else ""
    return SshRunner(entry.host, entry.port, entry.user,
                     password=password, key_path=entry.key_path)


class ServerManager:
    """Registry + SSH actions; secrets stay in the OS credential store."""

    def __init__(self, store: ServerStore | None = None,
                 secrets: SecretStore | None = None,
                 runner_factory: Callable[[ServerEntry, str], Runner] | None = None):
        self.store = store or ServerStore()
        self.secrets = secrets or SecretStore()
        self.runner_factory = runner_factory or default_runner_factory

    # -- registry --------------------------------------------------------
    def list(self) -> list[ServerEntry]:
        return self.store.list()

    def resolve(self, ref: str) -> ServerEntry:
        entry = self.store.find(ref)
        if entry is None:
            raise ServerError(f"Сервер не найден: {ref}")
        return entry

    def save(self, entry: ServerEntry) -> ServerEntry:
        return self.store.save(entry)

    def delete(self, server_id: str) -> None:
        self.store.delete(server_id)
        try:
            self.secrets.delete(self.secret_key(server_id))
        except Exception:
            pass

    # -- secrets ---------------------------------------------------------
    def secret_key(self, server_id: str) -> str:
        return f"server.{server_id}.password"

    def set_password(self, server_id: str, password: str) -> None:
        if not password:
            raise ServerError("Пароль не должен быть пустым.")
        self.secrets.set(self.secret_key(server_id), password)

    def has_password(self, server_id: str) -> bool:
        try:
            return bool(self.secrets.get(self.secret_key(server_id)))
        except RuntimeError:
            return False

    # -- actions ---------------------------------------------------------
    def _connect(self, entry: ServerEntry) -> Runner:
        secret = ""
        if entry.auth_kind == "password":
            try:
                secret = self.secrets.get(self.secret_key(entry.id))
            except RuntimeError:
                secret = ""
            if not secret:
                raise ServerError(
                    f"Для сервера «{entry.name}» не сохранён пароль SSH.")
        runner = self.runner_factory(entry, secret)
        runner.connect()
        return runner

    def _run(self, entry: ServerEntry, command: str,
             timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        runner = self._connect(entry)
        try:
            result = runner.run(command, timeout=timeout)
        finally:
            runner.close()
        result.setdefault("server", entry.name)
        return result

    def test_connection(self, ref: str) -> dict[str, Any]:
        entry = self.resolve(ref)
        runner = self._connect(entry)
        try:
            result = runner.run("echo connected && hostname",
                                timeout=_CONNECT_TIMEOUT + 5)
            fingerprint = str(getattr(runner, "host_fingerprint", "") or "")
            if fingerprint:
                result["host_fingerprint"] = fingerprint
                result["output"] = (result.get("output", "").rstrip()
                                    + f"\n[host key {fingerprint}]")
        finally:
            runner.close()
        result["ok"] = bool(result.get("ok"))
        result.setdefault("server", entry.name)
        return result

    def info(self, ref: str) -> dict[str, Any]:
        entry = self.resolve(ref)
        result = self._run(entry, INFO_COMMAND)
        result["info"] = result.get("output", "")
        return result

    def run_command(self, ref: str, command: str,
                    timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
        if not str(command).strip():
            raise ServerError("Команда не должна быть пустой.")
        entry = self.resolve(ref)
        return self._run(entry, command, timeout=timeout)

    # -- agent tools -------------------------------------------------------
    def agent_tools(self) -> tuple[dict[str, Any], list[dict[str, Any]],
                                   frozenset[str]]:
        def list_servers(_args: dict[str, Any]) -> dict[str, Any]:
            return {
                "ok": True,
                "servers": [
                    {"id": entry.id, "name": entry.name,
                     "address": entry.address, "auth": entry.auth_kind}
                    for entry in self.list()
                ],
            }

        def server_info(args: dict[str, Any]) -> dict[str, Any]:
            try:
                return self.info(str(args.get("server") or ""))
            except ServerError as exc:
                return {"ok": False, "error": str(exc)}

        def run_on_server(args: dict[str, Any]) -> dict[str, Any]:
            try:
                return self.run_command(
                    str(args.get("server") or ""),
                    str(args.get("command") or ""),
                    timeout=float(args.get("timeout_seconds") or DEFAULT_TIMEOUT),
                )
            except (ServerError, TypeError, ValueError) as exc:
                return {"ok": False, "error": str(exc)}

        handlers: dict[str, Any] = {
            "list_servers": list_servers,
            "server_info": server_info,
            "run_on_server": run_on_server,
        }
        schemas: list[dict[str, Any]] = [
            {"type": "function", "function": {
                "name": "list_servers",
                "description": "Список подключённых серверов (имя, адрес).",
                "parameters": {"type": "object", "properties": {}, "required": []}}},
            {"type": "function", "function": {
                "name": "server_info",
                "description": "Информация об удалённом сервере: система, GPU, диск, нагрузка.",
                "parameters": {"type": "object", "properties": {
                    "server": {"type": "string", "description": "Имя или id сервера"}},
                    "required": ["server"]}}},
            {"type": "function", "function": {
                "name": "run_on_server",
                "description": "Выполнить команду на удалённом сервере по SSH.",
                "parameters": {"type": "object", "properties": {
                    "server": {"type": "string", "description": "Имя или id сервера"},
                    "command": {"type": "string", "description": "Команда shell"},
                    "timeout_seconds": {"type": "number", "description": "Таймаут, сек"}},
                    "required": ["server", "command"]}}},
        ]
        return handlers, schemas, frozenset({"run_on_server"})


def time_marker() -> str:  # small helper kept for status stamps in the UI
    return time.strftime("%H:%M:%S")
