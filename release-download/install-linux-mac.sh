#!/bin/sh
# AlterEgo LLM Studio — Linux/macOS installer
set -eu
cd "$(dirname "$0")"

set -- alterego_training_hub_desktop-*-py3-none-any.whl
if [ ! -f "$1" ]; then
  echo "Wheel не найден. Скачайте alterego_training_hub_desktop-<version>-py3-none-any.whl из того же GitHub Release и положите рядом с этим скриптом." >&2
  exit 1
fi
if [ "$#" -ne 1 ]; then
  echo "Найдено несколько wheel-файлов. Оставьте рядом только wheel этой версии релиза." >&2
  exit 1
fi

python3 -m pip install "$1" cryptography
echo "Готово! Запуск: alterego-llm-studio"
