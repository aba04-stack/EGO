# AlterEgo Training Hub — LLM Studio

A desktop development environment for LLM research with an IDE layout: code editor and terminal in the center, a docked mentor-agent chat on the right, model/dataset library, training with live metrics, model playground, service connectors (GitHub / Hugging Face / Gmail), and RunPod GPU management — all in one Windows-first app.

## Interface

| Editor + terminal + agent chat | Model dashboard | Servers (SSH) |
| --- | --- | --- |
| ![IDE with agent chat](docs/ui-chat.png) | ![Dashboard](docs/ui-dashboard.png) | ![Servers](docs/ui-servers.png) |

Mockups are rendered from the app's real design tokens by `scripts/render_ui_mockup.py`. Settings panels at the top of pages collapse/expand (▼/▶) so the workspace stays clean.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+1`…`Ctrl+9` | Pages: editor, workspace, models, datasets, model, playground, training, GPU, servers |
| `Ctrl+0` | Settings |
| `Ctrl+P` | Quick open file (fuzzy) |
| `Ctrl+Shift+P` | Command palette |
| `Ctrl+Shift+F` | Search across the project |
| `Ctrl+K` | Focus the mentor chat |
| `Ctrl+J` | Collapse/expand the bottom panel |
| `Ctrl+Shift+M` | Problems panel |
| `Ctrl+W` | Close editor tab |
| `Ctrl+Tab` | Next editor tab |
| `F5` | Refresh the current page |
| `F1` | Shortcut help |
| `Ctrl+Enter` | Send a chat message |
| `Ctrl+S` | Save file in the editor |

## Editor, palette, search

The editor opens files in **IDE-style tabs** (each tab keeps its buffer, `•` marks unsaved changes, `Ctrl+W` closes, `Ctrl+Tab` cycles) with a cursor position readout and **syntax highlighting** (Python, YAML/JSON, plain text) on a dark code canvas. **Autocomplete** suggests words from the file and the Python vocabulary (`Tab`/`Enter` accepts, `Esc` closes, `↑`/`↓` navigates). **Ctrl+P** opens any workspace file by fuzzy name; **Ctrl+Shift+P** runs commands from one palette (navigation, training, diagnostics). **Ctrl+Shift+F** searches the workspace by regex and jumps straight to the matching line in the editor.

The bottom panel behaves like VS Code's: **ТЕРМИНАЛ** and **ПРОБЛЕМЫ** tabs (`Ctrl+Shift+M`, `Ctrl+J` collapses the panel). The Problems tab collects errors from training logs (tracebacks, `FAILED` tests, metric anomalies) and a double-click opens the exact file and line in the editor; the list can be sent to the mentor in one click. The status bar shows the current **Git branch** with a dirty marker.

## Diagnostics and logs

The **Диагностика** section on the settings page checks the environment (Python, Tk, credential store, paramiko, Git, workspace, disk space, mentor config) and produces a copyable report. Application errors are written to `<app data>/logs/hub.log` (rotated); uncaught crashes show a dialog with the log path.

## Studio features

**Разработка**
- **Редактор кода** — file tree of the workspace, built-in editor (Ctrl+S), "обсудить с наставником" for any file, and **project scaffolding from templates**: a ready-to-run `train.py` + `config.json` + `eval.py` (stdlib-only) whose metrics are parsed by the dashboard out of the box.
- **Рабочая папка** — pick one folder on your PC; all tools and training are confined to it. Git connect/clone/fetch/pull-ff/branch flows included.
- **Терминал** — a bottom panel to run any command in the workspace **or on a connected server** and watch the output, with one-click re-run from history; the panel itself can be collapsed.
- **Наставник-агент** (right panel) — a chat mentor that works as an **autonomous agent**: it can inspect and edit code, run commands, query training state, use connectors and even start/stop training to reach your goal. Two modes: *Ассистент* (every mutating action asks for confirmation) and *Режим агента* (acts freely toward the goal; everything is still backed up and logged).

**Библиотека**
- **Модели** — registry of local checkpoints (`*.safetensors`, `*.gguf`, …) and cloud artefacts (`s3://`, `hf://`, `runpod://`, `https://`), folder scanning, portable JSON manifests. The library folder can be a cloud-synced directory (OneDrive, Yandex.Disk, …).
- **Датасеты** — JSONL/CSV/TXT catalogue with row counts, sizes and previews.
- **Модель и прогресс** — model card, live training chart (loss/acc), trend verdicts, anomaly detection (NaN/Inf, divergence, stagnation), mentor assessment card (score, reasoning, what is good/bad, risks, recommendations) and a full activity trail.

**Эксперименты**
- **Playground** — probe any configured model with test prompts and compare A/B side by side with latency.
- **Обучение** — run training in the workspace, stream logs, auto-send failures to the mentor, persistent run history with metric snapshots and mentor scores. The mentor can query training state itself (status, log tail, run history).
- **Внешние GPU** — live RunPod catalog, GPU-rate budget gate (not a total-bill cap), confirmed pod lifecycle.

**Система**
- **Серверы** — подключение удалённых серверов по SSH: проверка связи, состояние системы (GPU/диск/нагрузка), выполнение команд вручную, из терминала или агентом. Пароли — только в системном хранилище; host-ключи проверяются (TOFU-pinning в `known_hosts`).
- **Коннекторы** — GitHub repository search, Hugging Face model search and model cards, Gmail notifications (SMTP with App Password). Tokens live only in the OS credential store; the same actions are exposed to the mentor-agent as tools.
- **Диагностика** — «Доктор» окружения: Python/Tk, keyring, SSH, Git, папки, диск; копируемый отчёт; лог ошибок `logs/hub.log` с ротацией.
- Settings panels at the top of pages are **collapsible** (hide/show) so the workspace stays clean; **keyboard shortcuts** (F1) for navigation, chat and the terminal.
- API keys only in the OS credential store (`keyring`); settings files contain no secrets.
- Automatic timestamped backups before mentor file edits; JSONL audit trail outside the repository.
- Package as a Windows executable using PyInstaller.

## Features

**Mentor agent with tools**
- Docked chat panel on the right with persistent dialogs (saved per user, no secrets inside).
- The agent can inspect the selected workspace: list/read/search files, edit files, and run commands. Assist mode requires explicit confirmation for every mutating action; **agent mode** performs the whole goal freely (plan → act → verify), while still backing up every edit and logging every call.
- Give the agent a goal ("запусти тесты, найди падающий, почини и проверь") and it loops through tools until the goal is done: it can start/stop training, read metrics and logs, search GitHub and Hugging Face, and send e-mail notifications.
- Works with any OpenAI-compatible provider that supports `tools`; a plain-text ` ```tool ` fallback protocol is used when function calling is unavailable.
- Quick commands: model assessment, training progress, log error triage. Structured assessments are saved to the model dashboard automatically.
- The mentor participates in training: send it a training log (or let the app do it automatically on failure) and it will find errors, read the code, and propose fixes. Every edit is backed up before it is applied.

**Remote servers (SSH)**
- Register any SSH-reachable machine (name, host, port, user, key or password auth) on the **Серверы** page; passwords live in the OS credential store, never in files.
- Test the connection, view system info (kernel, GPU, disk, load), and run arbitrary commands — from the page, from the terminal panel (target selector: Локально / server), or through the mentor-agent (`list_servers`, `server_info`, `run_on_server`).
- Host keys are verified against the system known_hosts plus an app-managed pin file (`known_hosts`, trust-on-first-use, `SHA256:…` fingerprint shown); a changed host key is rejected. Remote output is size-capped.
- The transport is paramiko (installed with the app); the registry is a plain JSON file you can edit or sync.

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
- An SSH-reachable server is optional (the `paramiko` package is installed with the app).

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

Then use the **Наставник** panel on the right: talk to the mentor, ask it to read your project, find bugs, run tests, or fix code. It can only touch the folder you selected on the **Рабочая папка** page. In *Ассистент* mode every file change or command execution is shown for your confirmation before it happens; in *Режим агента* it acts towards your goal without step-by-step confirmations — review its work via the activity trail and backups (use Git to diff and roll back).

Only use mentor outputs for model development if the selected API/model terms permit that use. Do not send private training data without checking the provider's data handling and terms.

## Connect services (GitHub, Hugging Face, Gmail)

Open the **Коннекторы** page. Tokens and passwords go straight to the OS credential store; nothing is written to settings files. For Gmail use an App Password (Google Account → Security → 2-Step Verification → App passwords) — the app sends through SMTP with STARTTLS. The same connectors are available to the mentor-agent as tools: `search_github`, `search_huggingface`, `huggingface_model_card`, `send_email`.

## Connect cloud GPUs

In the **Внешние GPU** tab, save a RunPod key, refresh the catalog, and select an exact GPU ID. The app reads the provider's current catalog rate before showing a confirmation dialog. The displayed limit covers only the catalog GPU rate, not a guaranteed total bill. Storage, networking, taxes, and other charges can apply. Container-disk data may be lost when a pod is deleted, so copy checkpoints to durable storage.

RunPod REST API v2 is in public beta; this adapter may need maintenance when the provider changes its API.

## Scope and honest limitations

This is a desktop control-plane MVP, not yet an end-to-end training orchestration product. It does not yet copy the selected AI repository to a remote worker, upload datasets, launch training on a cloud GPU, stream remote logs, enforce a total-spend ceiling, or synchronize/resume remote checkpoints. Training runs locally in the chosen workspace folder; cloud resource management is implemented separately. Do not assume that creating a pod starts training. The mentor's file edits are ordinary file writes — in assist mode they are confirmed explicitly, in agent mode they are only backed up and logged, so use Git to review and roll them back.

The next milestone is a typed remote training worker with resumable checkpoint/data transfers, explicit elapsed-time and total-cost guards, live logs, and end-to-end tests on a short disposable job.

## Tests

```powershell
python -m compileall -q src run_app.py tests
python -m pytest -q
```

GitHub Actions runs compilation and unit tests on pushes and pull requests.
