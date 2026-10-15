"""Этап G: подпись, anti-rollback, атомарность и откат — поведением."""
from __future__ import annotations

import os

import pytest

try:
    import cryptography  # noqa: F401
except ImportError:
    if os.environ.get("ALTEREGO_REQUIRE_CRYPTO") == "1":
        # Релизный прогон: пропуск G-тестов недопустим, падаем громко.
        raise RuntimeError(
            "ALTEREGO_REQUIRE_CRYPTO=1, а cryptography не установлен: "
            "подписанные обновления нельзя проверять пропуском.")
    pytest.skip("cryptography не установлен", allow_module_level=True)

from alterego_training_hub.signed_update import (
    SignedUpdateError,
    apply_update,
    build_manifest,
    generate_keypair,
    rollback,
    sign_manifest,
    verify_manifest,
)


@pytest.fixture()
def keys():
    return generate_keypair()  # (private, public)


def _signed(tmp_path, keys, version="2.0.0", content=b"new-binary"):
    artifact = tmp_path / "app.bin"
    artifact.write_bytes(content)
    manifest = build_manifest(version=version, artifact=artifact,
                              url="https://example.com/app.bin")
    return sign_manifest(manifest, keys[0]), artifact


def test_apply_and_rollback(tmp_path, keys):
    manifest, artifact = _signed(tmp_path, keys)
    target = tmp_path / "installed.bin"
    target.write_bytes(b"old-binary")
    result = apply_update(manifest=manifest, artifact=artifact,
                          target=target, current_version="1.0.0",
                          public_key_pem=keys[1])
    assert target.read_bytes() == b"new-binary"
    assert result["applied"] == "2.0.0"
    assert not target.with_suffix(".bin.part").exists()
    assert rollback(target) is True
    assert target.read_bytes() == b"old-binary"


def test_tampered_artifact_rejected(tmp_path, keys):
    manifest, artifact = _signed(tmp_path, keys)
    artifact.write_bytes(b"evil-binary!!")
    target = tmp_path / "installed.bin"
    with pytest.raises(SignedUpdateError, match="SHA-256"):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.0.0", public_key_pem=keys[1])
    assert not target.exists()


def test_tampered_manifest_breaks_signature(tmp_path, keys):
    manifest, _artifact = _signed(tmp_path, keys)
    manifest["version"] = "9.9.9"  # подпись считалась по исходному
    with pytest.raises(SignedUpdateError, match="Подпись"):
        verify_manifest(manifest, keys[1])


def test_anti_rollback_rejects_older(tmp_path, keys):
    manifest, artifact = _signed(tmp_path, keys, version="1.0.0")
    target = tmp_path / "installed.bin"
    with pytest.raises(SignedUpdateError, match="Anti-rollback"):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.13.0", public_key_pem=keys[1])


def test_wrong_key_rejected(tmp_path, keys):
    manifest, _ = _signed(tmp_path, keys)
    _, other_public = generate_keypair()
    with pytest.raises(SignedUpdateError):
        verify_manifest(manifest, other_public)


def _installed(tmp_path, keys, version="2.0.0"):
    manifest, artifact = _signed(tmp_path, keys, version=version)
    target = tmp_path / "installed.bin"
    target.write_bytes(b"old-binary")
    return manifest, artifact, target


@pytest.mark.parametrize("patch", [
    {"schema": 2}, {"schema": "1"}, {"version": ""}, {"version": "скоро"},
    {"version": 200}, {"version": None}, {"url": ""}, {"url": 42},
    {"sha256": "zz"}, {"sha256": "a" * 63}, {"sha256": 7},
    {"size": "9"}, {"size": 0}, {"size": -3}, {"size": True},
    {"size": 9.5}, {"signature": ""}, {"signature": None},
])
def test_malformed_manifests_rejected(tmp_path, keys, patch):
    manifest, artifact, target = _installed(tmp_path, keys)
    manifest.update(patch)
    with pytest.raises(SignedUpdateError):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.0.0", public_key_pem=keys[1])
    assert target.read_bytes() == b"old-binary"


def test_manifest_not_a_dict_and_truncated_signature(tmp_path, keys):
    manifest, artifact, target = _installed(tmp_path, keys)
    with pytest.raises(SignedUpdateError):
        apply_update(manifest=["не", "словарь"], artifact=artifact,
                     target=target, current_version="1.0.0",
                     public_key_pem=keys[1])
    manifest["signature"] = manifest["signature"][:20] + "!!"
    with pytest.raises(SignedUpdateError):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.0.0", public_key_pem=keys[1])
    assert target.read_bytes() == b"old-binary"


def test_size_mismatch_after_signing_rejected(tmp_path, keys):
    manifest, artifact, target = _installed(tmp_path, keys)
    artifact.write_bytes(b"new-binary-longer")
    # хэш и размер больше не совпадут с подписанными
    with pytest.raises(SignedUpdateError):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.0.0", public_key_pem=keys[1])
    assert target.read_bytes() == b"old-binary"


def test_write_error_keeps_target_and_cleans_tmp(tmp_path, keys, monkeypatch):
    from alterego_training_hub import signed_update

    manifest, artifact, target = _installed(tmp_path, keys)

    def boom(*a, **k):
        raise OSError("диск переполнен")

    monkeypatch.setattr(signed_update.shutil, "copyfileobj", boom)
    with pytest.raises(OSError):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.0.0", public_key_pem=keys[1])
    assert target.read_bytes() == b"old-binary"
    assert list(tmp_path.glob("*.part")) == []
    assert not (tmp_path / "installed.bin.update.lock").exists()


def test_replace_error_keeps_target(tmp_path, keys, monkeypatch):
    from alterego_training_hub import signed_update

    manifest, artifact, target = _installed(tmp_path, keys)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if str(dst) == str(target):
            raise OSError("замена не удалась")
        return real_replace(src, dst)

    monkeypatch.setattr(signed_update.os, "replace", flaky)
    with pytest.raises(OSError):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.0.0", public_key_pem=keys[1])
    assert target.read_bytes() == b"old-binary"
    assert list(tmp_path.glob("*.part")) == []
    # .bak создан до замены и равен прежнему содержимому
    assert (tmp_path / "installed.bin.bak").read_bytes() == b"old-binary"


def test_backup_matches_previous_and_rollback_restores(tmp_path, keys):
    manifest, artifact, target = _installed(tmp_path, keys)
    apply_update(manifest=manifest, artifact=artifact, target=target,
                 current_version="1.0.0", public_key_pem=keys[1])
    assert (tmp_path / "installed.bin.bak").read_bytes() == b"old-binary"
    assert rollback(target) is True
    assert target.read_bytes() == b"old-binary"
    assert rollback(target) is False  # второй откат: .bak уже израсходован


def test_concurrent_update_rejected_by_lock(tmp_path, keys):
    manifest, artifact, target = _installed(tmp_path, keys)
    lock = tmp_path / "installed.bin.update.lock"
    lock.write_text("pid=999", encoding="utf-8")
    with pytest.raises(SignedUpdateError, match="замок"):
        apply_update(manifest=manifest, artifact=artifact, target=target,
                     current_version="1.0.0", public_key_pem=keys[1])
    assert target.read_bytes() == b"old-binary"
    lock.unlink()
    apply_update(manifest=manifest, artifact=artifact, target=target,
                 current_version="1.0.0", public_key_pem=keys[1])
    assert target.read_bytes() == b"new-binary"


def test_no_part_leftovers_after_success(tmp_path, keys):
    manifest, artifact, target = _installed(tmp_path, keys)
    apply_update(manifest=manifest, artifact=artifact, target=target,
                 current_version="1.0.0", public_key_pem=keys[1])
    assert list(tmp_path.glob("*.part*")) == []


def test_private_key_scan_and_cli_permissions(tmp_path):
    from alterego_training_hub.signed_update import scan_for_private_keys

    secret = tmp_path / "dist" / "private.pem"
    secret.parent.mkdir()
    secret.write_text("-----BEGIN PRIVATE KEY-----\nx\n", encoding="utf-8")
    leaks = scan_for_private_keys([tmp_path / "dist"])
    assert leaks and "private" in leaks[0].lower()
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "public.pem").write_text("-----BEGIN PUBLIC KEY-----\n",
                                      encoding="utf-8")
    assert scan_for_private_keys([clean]) == []

    import stat as stat_mod
    import subprocess
    import sys

    keys_dir = tmp_path / "keys"
    done = subprocess.run(
        [sys.executable, "scripts/sign_update.py", "make-keys",
         "--out-dir", str(keys_dir)],
        capture_output=True, text=True, timeout=120, cwd=".")
    assert done.returncode == 0, done.stderr
    if os.name == "posix":
        mode = stat_mod.S_IMODE((keys_dir / "private.pem").stat().st_mode)
        assert mode == 0o600, oct(mode)
    bad = subprocess.run(
        [sys.executable, "scripts/sign_update.py", "check",
         str(tmp_path / "dist")],
        capture_output=True, text=True, timeout=120, cwd=".")
    assert bad.returncode == 1
    assert "НАЙДЕНЫ ЗАКРЫТЫЕ КЛЮЧИ" in bad.stdout
    good = subprocess.run(
        [sys.executable, "scripts/sign_update.py", "check", str(clean)],
        capture_output=True, text=True, timeout=120, cwd=".")
    assert good.returncode == 0, good.stdout + good.stderr
    assert "не найдено" in good.stdout
