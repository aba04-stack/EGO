# AlterEgo Training Hub — LLM Studio

A desktop development environment for LLM research: chat mentor with code tools, code editor, model/dataset library, training with live metrics, model playground, and RunPod GPU management — all in one Windows-first app.

## Interface

| Chat with mentor | Model dashboard |
| --- | --- |
| ![Chat](docs/ui-chat.png) | ![Dashboard](docs/ui-dashboard.png) |

Mockups are rendered from the app's real design tokens by `scripts/render_ui_mockup.py`.

## Studio features

**Разработка**
- **Чат с наставником** — conversational panel with persistent dialogs; the mentor reads/searches/edits code and runs commands inside the chosen workspace (sandboxed, every mutation confirmed). Quick commands: model assessment, training progress, log error triage.
- **Редактор кода** — file tree of the workspace, built-in editor (Ctrl+S), "обсудить с наставником" for any file, and **project scaffolding from templates**: a ready-to-run `train.py` + `config.json` + `eval.py` (stdlib-only) whose metrics are parsed by the dashboard out of the box.
- **Рабочая папка** — pick one folder on your PC; all tools and training are confined to it. Git connect/clone/fetch/pull-ff/branch flows included.

**Библиотека**
- **Модели** — registry of local checkpoints (`*.safetensors`, `*.gguf`, …) and cloud artefacts (`s3://`, `hf://`, `runpod://`, `https://`), folder scanning, portable JSON manifests. The library folder can be a cloud-synced directory (OneDrive, Yandex.Disk, …).
- **Датасеты** — JSONL/CSV/TXT catalogue with row counts, sizes and previews.
- **Модель и прогресс** — model card, live training chart (loss/acc), trend verdicts, anomaly detection (NaN/Inf, divergence, stagnation), mentor assessment card (score, reasoning, what is good/bad, risks, recommendations) and a full activity trail.

**Эксперименты**
- **Playground** — probe any configured model with test prompts and compare A/B side by side with latency.
- **Обучение** — run training in the workspace, stream logs, auto-send failures to the mentor, persistent run history with metric snapshots and mentor scores. The mentor can query training state itself (status, log tail, run history).
- **Внешние GPU** — live RunPod catalog, GPU-rate budget gate (not a total-bill cap), confirmed pod lifecycle.

**Система**
- API keys only in the OS credential store (`keyring`); settings files contain no secrets.
- Automatic timestamped backups before mentor file edits; JSONL audit trail outside the repository.
- Package as a Windows executable using PyInstaller.

## Features

**Chat mentor with tools**
- Conversational panel with persistent dialogs (saved per user, no secrets inside).
- The mentor can inspect the selected workspace: list/read/search files, edit files, and run commands — every mutating action requires explicit confirmation.
- The mentor can also query training state (current metrics, log tail, run history) even without a workspace.
- Works with any OpenAI-compatible provider that supports `tools`; a plain-text ` ```tool ` fallback protocol is used when function calling is unavailable.
- Quick commands: model assessment, training progress, log error triage. Structured assessments are saved to the model dashboard automatically.
- The mentor participates in training: send it a training log (or let the app do it automatically on failure) and it will find errors, read the code, and propose fixes. Every edit is backed up before it is applied.

**Training progress and metrics**
- Parses logs for loss/accuracy/lr series, epoch progress, and draws a live chart.
- Trend analysis (улучшается / ухудшается / стабильно) and anomaly detection: NaN/Inf, divergence, stagnation.
- Persistent run history with exit codes, metric snapshots, and mentor scores.

**Model dashboard**
- Model card (kind, location, API id, metrics, notes), training progress with chart, and a full activity feed of actions (training runs, mentor tool calls, file edits, saved reports).
- Mentor assessment card: score 0–10, reasoning, what is good, what is bad, risks, recommendations — rendered as a structured report and exportable to Markdown.

**Models registry**
- Catalogue of models: local checkpoints (`*.safetensors`, `*.gguf`, …) and cloud artefacts (`s3://`, `hf://`, `runpod://`, `https://`).
- The library folder can point at a cloud-synced directory (OneDrive, Google Drive, Yandex.Disk) to keep the catalogue in the cloud.
- Scan folders for checkpoints, export/import a portable JSON manifest.

**Cloud GPUs and security**
- Browse the live RunPod GPU catalog and list GPU pods.
- Preview GPU pricing against a configured GPU-only hourly limit. Creating, stopping, resuming, or deleting cloud resources requires explicit confirmation. The limit is not a total-bill cap.
- Store API keys in the operating-system credential store through `keyring`; keys are not written into the project settings file or Git repository.
- Package as a Windows executable using PyInstaller.

## Requirements

- Windows 10/11 recommended for the first desktop build.
- Python 3.10 or newer for running from source.
- Git for Windows and a working credential helper for private repositories.
- A RunPod API key only if using RunPod features.
- An API key and model ID for an OpenAI-compatible mentor provider.

## Run from source

From PowerShell in the repository directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python run_app.py
```

For private GitHub repositories, authenticate with Git Credential Manager or GitHub CLI before cloning. Do not embed a token in a repository URL.

## Create the Windows application

In PowerShell:

```powershell
.\scripts\build_windows.ps1
```

The build script creates `dist\AlterEgoTrainingHub.exe`. Build and test it on Windows before distributing it. A Windows executable should be built on Windows; the source checkout itself is cross-platform only where Tkinter and an appropriate credential-store backend are available.

## Connect a mentor

In the **Настройки** page, enter the provider's HTTPS OpenAI-compatible base URL (usually ending in `/v1`), fetch the model list or type the exact model ID, and save its key. Saving the key uses the operating-system credential store. The connection-test button asks for confirmation before sending (it may consume API credits).

Then open the **Чат с наставником** page: talk to the mentor, ask it to read your project, find bugs, run tests, or fix code. It can only touch the folder you selected on the **Рабочая папка** page, and every file change or command execution is shown for your confirmation before it happens.

Only use mentor outputs for model development if the selected API/model terms permit that use. Do not send private training data without checking the provider's data handling and terms.

## Connect cloud GPUs

In the **Внешние GPU** tab, save a RunPod key, refresh the catalog, and select an exact GPU ID. The app reads the provider's current catalog rate before showing a confirmation dialog. The displayed limit covers only the catalog GPU rate, not a guaranteed total bill. Storage, networking, taxes, and other charges can apply. Container-disk data may be lost when a pod is deleted, so copy checkpoints to durable storage.

RunPod REST API v2 is in public beta; this adapter may need maintenance when the provider changes its API.

## Scope and honest limitations

This is a desktop control-plane MVP, not yet an end-to-end training orchestration product. It does not yet copy the selected AI repository to a remote worker, upload datasets, launch training on a cloud GPU, stream remote logs, enforce a total-spend ceiling, or synchronize/resume remote checkpoints. Training runs locally in the chosen workspace folder; cloud resource management is implemented separately. Do not assume that creating a pod starts training. The mentor's file edits always require confirmation and are ordinary file writes — use Git to review and roll them back.

The next milestone is a typed remote training worker with resumable checkpoint/data transfers, explicit elapsed-time and total-cost guards, live logs, and end-to-end tests on a short disposable job.

## Tests

```powershell
python -m compileall -q src run_app.py tests
python -m pytest -q
```

GitHub Actions runs compilation and unit tests on pushes and pull requests.
