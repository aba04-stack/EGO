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
    args = parser.parse_args()
    if args.cmd == "make-keys":
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        private, public = generate_keypair()
        (out_dir / "private.pem").write_bytes(private)
        (out_dir / "public.pem").write_bytes(public)
        print(f"Ключи: {out_dir}/private.pem (СЕКРЕТ) и public.pem")
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
