# A0 — фиксация состояния коммита 31baec9 (v1.8.7)

Дата проверки: 2026-10-14. Рабочее дерево сверено с коммитом `31baec9`
(`git diff --cached 31baec9` пуст — содержание идентично).

## Окружение
- Linux-6.1.158+ x86_64, Intel Xeon @ 2.60GHz, 2 CPU, 3.9 ГБ RAM, без GPU.
- Python 3.11, torch 2.5.1+cu124 (CPU-режим), transformers 4.46.3,
  peft 0.13.2, trl 0.12.2, datasets 3.1.0, accelerate 1.1.1,
  tokenizers 0.20.3, numpy 2.4.6.

## Результаты
| Проверка | Команда | Итог |
|---|---|---|
| Тесты | `.venv/bin/python -m pytest tests/ -q` | **PASS — 470 passed** |
| Линтер | `.venv/bin/ruff check src tests scripts examples` | **PASS** |
| Типы | `.venv/bin/python -m mypy` | **PASS (19 файлов)** |
| Сборка пакета | `.venv/bin/python -m build --wheel` | **PASS — alterego_training_hub_desktop-1.8.7-py3-none-any.whl** |
| Реальная проверка | `.venv/bin/python scripts/real_check.py --require-torch` | **PASS — 18 ✓ / 0 ✗, exit 0** (scratch loss 1.03→~0.3–0.5, LoRA val_loss≈3.36, адаптер сохранён) |
| Настоящий Tk | — | **BLOCKED** — нет tkinter/дисплея в песочнице; в CI это xvfb job |
| Живой RunPod | — | **BLOCKED** — нет разрешения на платные ресурсы и ключа API |
| GPU/BF16 на железе | — | **BLOCKED** — нет GPU; логика выбора dtype покрыта кодом, не железом |
| LLaMA-Factory CLI | — | **BLOCKED (этап A)** — не установлен в окружении; в рейтинг не включён |

Пропусков внутри pytest: только условные skip при отсутствии опциональных
зависимостей в минимальном окружении; в этом окружении зависимости стоят.
