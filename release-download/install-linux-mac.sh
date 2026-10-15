#!/bin/sh
# EGO — Linux/macOS installer
set -eu
cd "$(dirname "$0")"

set -- ego_desktop-*-py3-none-any.whl
if [ ! -f "$1" ]; then
  echo "Wheel не найден. Скачайте ego_desktop-<version>-py3-none-any.whl из того же GitHub Release и положите рядом с этим скриптом." >&2
  exit 1
fi
if [ "$#" -ne 1 ]; then
  echo "Найдено несколько wheel-файлов. Оставьте рядом только wheel этой версии релиза." >&2
  exit 1
fi

if python3 -m pip show alterego-training-hub-desktop >/dev/null 2>&1; then
  echo "Перенос старой установки на EGO…"
  python3 -m pip uninstall -y alterego-training-hub-desktop
fi

python3 -m pip install "$1" cryptography
echo "Готово! Запуск: ego"
