#!/bin/sh
# EGO 1.16.0 — установка на Linux/macOS
set -e
cd "$(dirname "$0")"
python3 -m pip install "ego-1.16.0-py3-none-any.whl" cryptography
echo "Готово! Запуск: ego"
