#!/bin/sh
# AlterEgo LLM Studio 1.15.0 — установка на Linux/macOS
set -e
cd "$(dirname "$0")"
python3 -m pip install "alterego_training_hub_desktop-1.15.0-py3-none-any.whl" cryptography
echo "Готово! Запуск: alterego-llm-studio"
