#!/usr/bin/env python3
"""Релизный инструмент этапа G: ключи и подпись манифеста обновления.

  python scripts/sign_update.py make-keys --out-dir keys/
  python scripts/sign_update.py sign --artifact app.zip --version 1.14.0 \
      --url https://example.com/app.zip --key keys/private.pem \
      --out manifest.json

Приватный ключ не коммитить: держите в секретах CI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alterego_training_hub.signed_update import (
    build_manifest,
    generate_keypair,
    scan_for_private_keys,
    sign_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    keys = sub.add_parser("make-keys")
    keys.add_argument("--out-dir", default="keys")
    sign = sub.add_parser("sign")
    sign.add_argument("--artifact", required=True)
    sign.add_argument("--version", required=True)
    sign.add_argument("--url", required=True)
    sign.add_argument("--key", required=True)
    sign.add_argument("--out", default="manifest.json")
    check = sub.add_parser("check")
    check.add_argument("paths", nargs="+",
                       help="файлы/каталоги для поиска закрытых ключей")
    args = parser.parse_args()
    if args.cmd == "check":
        leaks = scan_for_private_keys([Path(x) for x in args.paths])
        if leaks:
            print("НАЙДЕНЫ ЗАКРЫТЫЕ КЛЮЧИ:")
            print("\n".join(leaks))
            return 1
        print("Закрытых ключей не найдено.")
        return 0
    if args.cmd == "make-keys":
        import os

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(out_dir, 0o700)
        except OSError:
            pass
        private, public = generate_keypair()
        # Закрытый ключ: 0600 с момента создания, а не после записи.
        fd = os.open(out_dir / "private.pem",
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(private)
        try:
            os.chmod(out_dir / "private.pem", 0o600)
        except OSError:
            pass
        (out_dir / "public.pem").write_bytes(public)
        print(f"Ключи: {out_dir}/private.pem (СЕКРЕТ, права 0600) и public.pem")
        return 0
    manifest = build_manifest(version=args.version,
                              artifact=Path(args.artifact), url=args.url)
    signed = sign_manifest(manifest, Path(args.key).read_bytes())
    Path(args.out).write_text(
        json.dumps(signed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"Манифест подписан: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
