# AlterEgo Training Hub Desktop

A Windows-first desktop control panel for managing AI-model research from a laptop. It can connect local Git workspaces, clone remote repositories, work with an AI mentor through a chat panel, catalogue models locally and in cloud storage, run training jobs with mentor-assisted debugging, and inspect/manage RunPod GPU resources.

## Features

**Chat mentor with tools**
- Conversational panel with persistent dialogs (saved per user, no secrets inside).
- The mentor can inspect the selected workspace: list/read/search files, edit files, and run commands — every mutating action requires explicit confirmation.
- Works with any OpenAI-compatible provider that supports `tools`; a plain-text ` ```tool ` fallback protocol is used when function calling is unavailable.
- The mentor participates in training: send it a training log (or let the app do it automatically on failure) and it will find errors, read the code, and propose fixes.

**Workspace**
- Choose one working folder on your PC; all mentor tools and training runs are sandboxed inside it (no shell, no path escapes).
- Connect an existing local Git repository or clone an HTTPS/SSH repository URL.
- Show current branch, remote, and uncommitted changes; fetch and pull using fast-forward-only mode; switch branches only when the worktree is clean.

**Models registry**
- Catalogue of models: local checkpoints (`*.safetensors`, `*.gguf`, …) and cloud artefacts (`s3://`, `hf://`, `runpod://`, `https://`).
- The library folder can point at a cloud-synced directory (OneDrive, Google Drive, Yandex.Disk) to keep the catalogue in the cloud.
- Scan folders for checkpoints, export/import a portable JSON manifest.

**Training**
- Run a training command inside the workspace, stream logs, stop safely.
- On failure, the log can be sent to the mentor for analysis — automatically or on demand.

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
