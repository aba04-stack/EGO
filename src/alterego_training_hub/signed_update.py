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
import shutil
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


def verify_manifest(manifest: dict[str, Any], public_key_pem: bytes) -> None:
    """Бросает SignedUpdateError при любой проблеме; молча не пропускает."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization

    _, Ed25519PublicKey = _ed25519()
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise SignedUpdateError("Манифест: нет schema=1.")
    for field in ("version", "url", "sha256", "size", "signature"):
        if not manifest.get(field):
            raise SignedUpdateError(f"Манифест: нет поля {field}.")
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


def apply_update(*, manifest: dict[str, Any], artifact: Path,
                 target: Path, current_version: str,
                 public_key_pem: bytes,
                 allow_downgrade: bool = False) -> dict[str, Any]:
    """Проверить и атомарно применить; старый файл остаётся в `.bak`."""
    verify_manifest(manifest, public_key_pem)
    version = str(manifest["version"])
    if not allow_downgrade and not is_newer(version, current_version):
        raise SignedUpdateError(
            f"Anti-rollback: версия {version} не новее текущей "
            f"{current_version}; обновление отклонено.")
    artifact, target = Path(artifact), Path(target)
    if not artifact.is_file():
        raise SignedUpdateError(f"Артефакт не найден: {artifact}")
    actual = sha256_file(artifact)
    if actual != str(manifest["sha256"]).lower():
        raise SignedUpdateError(
            "SHA-256 артефакта не совпал с манифестом — файл повреждён "
            "или подменён, обновление отклонено.")
    if artifact.stat().st_size != int(manifest["size"]):
        raise SignedUpdateError("Размер артефакта не совпал с манифестом.")
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + ".bak")
    if target.exists():
        shutil.copy2(target, backup)
    tmp = target.with_suffix(target.suffix + ".part")
    with artifact.open("rb") as src, tmp.open("wb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
    os.replace(tmp, target)  # атомарная замена в том же каталоге
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
