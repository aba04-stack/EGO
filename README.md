# EGO

**EGO — студия для обучения LLM.** Настольная программа: данные, запуск
обучения (SFT / LoRA / с нуля), живые метрики, чекпоинты, оценка и
наставник рядом с логом. Не чат «для дома» — конвейер, чтобы обучить
свою языковую модель.

EGO is a desktop studio **for training LLMs**: datasets, SFT/LoRA (or
train-from-scratch), live metrics, checkpoints, evaluation, and a mentor
next to the training log. It is not a home chatbot.

> **Experimental project — no warranty.** The program may be incomplete or
> unstable. Use it at your own risk.
>
> **Экспериментальный проект — без гарантий.** Программа может содержать
> ошибки. Используйте на свой риск.

Назначение подробно: [docs/PURPOSE.md](docs/PURPOSE.md).

## Интерфейс / Interface

![Screenshot of the real EGO desktop app running in CI](docs/screenshots/ego-main.png)

*Скриншот обновляется в CI после изменений UI.*

## Последняя версия / Latest version

**1.15.2**

## Скачать / Download

**[Скачать Windows x64 (.zip)](https://github.com/aba04-stack/EGO/releases/latest/download/EGO-Windows-x64.zip)** — распакуйте архив и запустите `EGO.exe`. Python не нужен.

[Все файлы последней версии / All release files](https://github.com/aba04-stack/EGO/releases/latest) — в разделе **Assets**:

- **Windows с Python:** `ego_desktop-*.whl` и `install-windows.bat` из одного релиза.
- **Linux / macOS:** `ego_desktop-*.whl` и `install-linux-mac.sh` из одного релиза.
- **Исходный код / Source:** `ego_desktop-*.tar.gz` или файлы репозитория.

Для установки через Python рекомендуется Python 3.11 или 3.12. Инструкции: [УСТАНОВКА.md](release-download/УСТАНОВКА.md). Файлы установщика и wheel должны быть скачаны **из одного и того же релиза**.

[История изменений / Changelog](CHANGELOG.md) · [Зачем EGO / Purpose](docs/PURPOSE.md) · [Исходный код](https://github.com/aba04-stack/EGO).
