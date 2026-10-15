"""Подписанные атомарные обновления (этап G).

Поток: релиз собирает артефакт -> `build_manifest` (версия, URL, SHA-256,
размер) -> подпись Ed25519 закрытым ключом релизера -> приложение
проверяет манифест открытым ключом, сверяет SHA-256 скачанного файла,
отвергает версии не новее текущей (anti-rollback) и заменяет файл
атомарно (`os.replace` в том же каталоге), сохраняя `.bak` для отката.

Без пакета cryptography подпись проверить нечем — обновление честно
отклоняется, а не применяется «на веру». HTTP здесь нет: скачивание
делает вызывающий код, сюда приходит локальный файл.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from .update_check import is_newer

SCHEMA = 1


class SignedUpdateError(RuntimeError):
    """Отказ обновления с понятной причиной."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(*, version: str, artifact: Path, url: str) -> dict[str, Any]:
    artifact = Path(artifact)
    return {"schema": SCHEMA, "version": str(version), "url": str(url),
            "sha256": sha256_file(artifact), "size": artifact.stat().st_size}


def _canonical(manifest: dict[str, Any]) -> bytes:
    payload = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise SignedUpdateError(
            "Нет пакета cryptography — подписанное обновление недоступно "
            "(pip install cryptography).") from exc
    return Ed25519PrivateKey, Ed25519PublicKey


def generate_keypair() -> tuple[bytes, bytes]:
    """(private_pem, public_pem) для релизера; приватный не покидает CI."""
    from cryptography.hazmat.primitives import serialization

    Ed25519PrivateKey, _ = _ed25519()
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public


def sign_manifest(manifest: dict[str, Any], private_key_pem: bytes) -> dict[str, Any]:
    from cryptography.hazmat.primitives import serialization

    Ed25519PrivateKey, _ = _ed25519()
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SignedUpdateError("Ключ подписи — не Ed25519.")
    signed = dict(manifest)
    signed["signature"] = base64.b64encode(
        key.sign(_canonical(manifest))).decode("ascii")
    return signed


_VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _validate_manifest_fields(manifest: Any) -> None:
    """Строгие типы ДО проверки подписи: мусор не доходит до криптографии."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise SignedUpdateError("Манифест: нет schema=1.")
    version = manifest.get("version")
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise SignedUpdateError(
            f"Манифест: некорректная версия {version!r} (нужна вида 1.2.3).")
    url = manifest.get("url")
    if not isinstance(url, str) or not url.strip():
        raise SignedUpdateError("Манифест: пустой или не строковый url.")
    sha = manifest.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha):
        raise SignedUpdateError("Манифест: sha256 — не 64 hex-символа.")
    size = manifest.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise SignedUpdateError(
            f"Манифест: size должен быть положительным int, не {size!r}.")
    if not isinstance(manifest.get("signature"), str) or not manifest["signature"]:
        raise SignedUpdateError("Манифест: нет подписи.")


def scan_for_private_keys(paths: list[Path]) -> list[str]:
    """Найти закрытые ключи в файлах/каталогах (сток в Git или релиз)."""
    leaks: list[str] = []
    for root in paths:
        root = Path(root)
        files = [root] if root.is_file() else (
            [f for f in root.rglob("*") if f.is_file()]
            if root.exists() else [])
        for f in files:
            name = f.name.lower()
            if name in {"private.pem", "private_key.pem"} or \
                    name.endswith(("_private.pem", "-private.pem")) or \
                    (name.endswith(".pem") and "private" in name):
                leaks.append(f"{f}: имя файла закрытого ключа")
                continue
            try:
                data = f.read_bytes()
            except OSError:
                continue
            if b"PRIVATE KEY-----" in data:
                leaks.append(f"{f}: содержимое закрытого ключа (PEM)")
    return leaks


def verify_manifest(manifest: dict[str, Any], public_key_pem: bytes) -> None:
    """Бросает SignedUpdateError при любой проблеме; молча не пропускает."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization

    _, Ed25519PublicKey = _ed25519()
    _validate_manifest_fields(manifest)
    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise SignedUpdateError("Открытый ключ — не Ed25519.")
    try:
        signature = base64.b64decode(str(manifest["signature"]), validate=True)
    except Exception as exc:
        raise SignedUpdateError("Манифест: подпись не base64.") from exc
    try:
        key.verify(signature, _canonical(manifest))
    except InvalidSignature as exc:
        raise SignedUpdateError(
            "Подпись манифеста недействительна (манифест изменён или "
            "подписан чужим ключом).") from exc


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass  # Windows/ФС без fsync каталога: замена всё равно атомарна


class _UpdateLock:
    """Эксклюзивный замок обновления с восстановлением после сбоя.

    Замок содержит pid и время. Если процесс-владелец мёртв ИЛИ замок
    старше `stale_after` секунд, замок считается зависшим: его атомарно
    переименовывают (rename выигрывает только один процесс) и создание
    повторяется. Живой свежий замок чужого процесса не удаляется никогда;
    при выходе замок снимается только если файл всё ещё наш (inode).
    """

    def __init__(self, target: Path, stale_after: float = 600.0):
        self.path = target.parent / (target.name + ".update.lock")
        self.stale_after = float(stale_after)
        self.fd: int | None = None

    def _try_create(self) -> bool:
        try:
            self.fd = os.open(self.path,
                              os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        os.write(self.fd,
                 f"pid={os.getpid()} time={time.time():.0f}".encode())
        os.fsync(self.fd)
        return True

    def _is_stale(self) -> bool:
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
            mtime_age = time.time() - self.path.stat().st_mtime
        except OSError:
            return False
        fields = dict(part.split("=", 1) for part in text.split()
                      if "=" in part)
        try:
            pid = int(fields.get("pid", "0"))
        except ValueError:
            pid = 0
        owner_dead = False
        # POSIX permits os.kill(pid, 0) as a liveness probe. On Windows,
        # signal value 0 is CTRL_C_EVENT, so this can interrupt the current
        # console process group instead of merely checking the PID.
        # On Windows, conservatively recover a lock only after its age expires.
        if pid > 0 and os.name != "nt":
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                owner_dead = True
            except OSError:
                owner_dead = False  # нет прав / иная ошибка: считаем живым
        expired = mtime_age > self.stale_after
        return owner_dead or expired

    def _recover_stale(self) -> bool:
        """Атомарно убрать зависший замок; чужие свежие не трогаем."""
        if not self._is_stale():
            return False
        graveyard = self.path.with_name(
            f"{self.path.name}.stale-{os.getpid()}")
        try:
            os.rename(self.path, graveyard)  # выиграет только один процесс
        except OSError:
            return False
        graveyard.unlink(missing_ok=True)
        return True

    def __enter__(self) -> _UpdateLock:
        if self._try_create():
            return self
        if self._recover_stale() and self._try_create():
            return self
        raise SignedUpdateError(
            "Уже идёт другое обновление этого файла (замок "
            f"{self.path.name}); дождитесь его завершения. Если процесс "
            "обновления аварийно завершился, замок будет признан "
            "зависшим по мёртвому pid или возрасту.")

    def __exit__(self, *exc: object) -> None:
        if self.fd is None:
            return
        try:
            mine = os.fstat(self.fd)
            try:
                current = self.path.stat()
                owned = (current.st_ino, current.st_dev) == \
                    (mine.st_ino, mine.st_dev)
            except OSError:
                owned = False
        finally:
            os.close(self.fd)
            self.fd = None
        if owned:
            try:
                self.path.unlink()
            except OSError:
                pass


def apply_update(*, manifest: dict[str, Any], artifact: Path,
                 target: Path, current_version: str,
                 public_key_pem: bytes,
                 allow_downgrade: bool = False,
                 lock_stale_after: float = 600.0) -> dict[str, Any]:
    """Проверить и атомарно применить; старый файл остаётся в `.bak`.

    Гарантии при любом отказе до `os.replace`: установленный файл не
    тронут, временный файл убран, `.bak` (если создан) равен прежнему
    содержимому байт-в-байт.
    """
    verify_manifest(manifest, public_key_pem)
    version = str(manifest["version"])
    if not allow_downgrade and not is_newer(version, current_version):
        raise SignedUpdateError(
            f"Anti-rollback: версия {version} не новее текущей "
            f"{current_version}; обновление отклонено.")
    artifact, target = Path(artifact), Path(target)
    if not artifact.is_file():
        raise SignedUpdateError(f"Артефакт не найден: {artifact}")
    if artifact.resolve() == target.resolve():
        raise SignedUpdateError("Артефакт и целевой файл совпадают.")
    actual = sha256_file(artifact)
    if actual != str(manifest["sha256"]).lower():
        raise SignedUpdateError(
            "SHA-256 артефакта не совпал с манифестом — файл повреждён "
            "или подменён, обновление отклонено.")
    if artifact.stat().st_size != int(manifest["size"]):
        raise SignedUpdateError("Размер артефакта не совпал с манифестом.")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + ".bak")
    tmp_name = ""
    with _UpdateLock(target, stale_after=lock_stale_after):
        try:
            if target.exists():
                # .bak тоже пишем атомарно и сверяем по хэшу до замены.
                with tempfile.NamedTemporaryFile(
                        mode="wb", dir=target.parent,
                        prefix=target.name + ".bak-", delete=False) as bak:
                    tmp_bak = Path(bak.name)
                    with target.open("rb") as src:
                        shutil.copyfileobj(src, bak)
                    bak.flush()
                    os.fsync(bak.fileno())
                try:
                    if sha256_file(tmp_bak) != sha256_file(target):
                        raise SignedUpdateError(
                            "Резервная копия не совпала с установленным "
                            "файлом — обновление прервано до замены.")
                    os.replace(tmp_bak, backup)
                finally:
                    tmp_bak.unlink(missing_ok=True)
            mode = (stat.S_IMODE(target.stat().st_mode)
                    if target.exists() else 0o644)
            with tempfile.NamedTemporaryFile(
                    mode="wb", dir=target.parent,
                    prefix=target.name + ".", suffix=".part",
                    delete=False) as dst:
                tmp_name = dst.name
                with artifact.open("rb") as src:
                    shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            os.chmod(tmp_name, mode)
            if sha256_file(Path(tmp_name)) != actual:
                raise SignedUpdateError(
                    "Временный файл повреждён при записи — обновление "
                    "прервано, установленный файл не тронут.")
            os.replace(tmp_name, target)  # атомарная замена, тот же каталог
            tmp_name = ""
            _fsync_dir(target.parent)
        finally:
            if tmp_name:
                Path(tmp_name).unlink(missing_ok=True)
    return {"applied": version, "target": str(target),
            "backup": str(backup) if backup.exists() else "",
            "sha256": actual}


def rollback(target: Path) -> bool:
    """Вернуть `.bak`, если он есть (тоже атомарно)."""
    target = Path(target)
    backup = target.with_suffix(target.suffix + ".bak")
    if not backup.is_file():
        return False
    os.replace(backup, target)
    return True
