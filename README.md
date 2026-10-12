# AlterEgo Training Hub Desktop

A Windows-first desktop control panel for managing AI-model research from a laptop. It can connect local Git workspaces, clone remote repositories, test an external API mentor, and inspect/manage RunPod GPU resources.

## MVP features

- Connect an existing local Git repository or clone an HTTPS/SSH repository URL.
- Show current branch, remote, and uncommitted changes; fetch and pull using fast-forward-only mode; switch branches only when the worktree is clean.
- Configure an OpenAI-compatible mentor endpoint and run an explicit connection test.
- Store API keys in the operating-system credential store through `keyring`; keys are not written into the project settings file or Git repository.
- Browse the live RunPod GPU catalog and list GPU pods.
- Preview GPU pricing against a configured GPU-only hourly limit. Creating, stopping, resuming, or deleting cloud resources requires explicit confirmation.
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

In the **ИИ-наставник** tab, enter the provider's HTTPS OpenAI-compatible base URL (usually ending in `/v1`), the exact model ID, and its key. Saving the key uses the operating-system credential store. The connection-test button sends the displayed test prompt and may consume API credits.

Only use mentor outputs for model development if the selected API/model terms permit that use. Do not send private training data without checking the provider's data handling and terms.

## Connect cloud GPUs

In the **Внешние GPU** tab, save a RunPod key, refresh the catalog, and select an exact GPU ID. The app reads the provider's current catalog rate before showing a confirmation dialog. The displayed limit covers only the catalog GPU rate, not a guaranteed total bill. Storage, networking, taxes, and other charges can apply. Container-disk data may be lost when a pod is deleted, so copy checkpoints to durable storage.

RunPod REST API v2 is in public beta; this adapter may need maintenance when the provider changes its API.

## Scope and honest limitations

This is an initial desktop control-plane MVP, not yet an end-to-end training orchestration product. It does not yet copy the selected AI repository to a remote worker, upload datasets, launch `scripts/train.py` on a cloud GPU, stream remote logs, enforce a total-spend ceiling, or synchronize/resume remote checkpoints. Cloud resource management and mentor testing are implemented separately from remote model training. Do not assume that creating a pod starts training.

The next milestone is a typed remote training worker with resumable checkpoint/data transfers, explicit elapsed-time and total-cost guards, live logs, and end-to-end tests on a short disposable job.

## Tests

```powershell
python -m compileall -q src run_app.py tests
python -m pytest -q
```

GitHub Actions runs compilation and unit tests on pushes and pull requests.
