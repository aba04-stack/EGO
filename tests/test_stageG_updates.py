"""Этап G: подпись, anti-rollback, атомарность и откат — поведением."""
from __future__ import annotations

import pytest

pytest.importorskip("cryptography")

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
