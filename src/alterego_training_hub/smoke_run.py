"""Smoke-run of a generated training script (этап 32).

Verifies the whole chain «wizard -> train_llm.py -> log formats -> app»
*without* a GPU or torch: the script is compiled, imported as a module, its
own ``load_texts`` runs against the real dataset, its ``log_sample`` emits a
line that our own parsers (:mod:`gen_preview`) must read back, and the
embedded CONFIG is checked for sanity.  Every failed check is a named
result — never an exception.

Pure stdlib; the inspected script is imported in-process (it is our own
generated file: stdlib-only at import time, torch/HF imports live inside
the training functions).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import py_compile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .gen_preview import parse_samples


@dataclass
class SmokeCheck:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class SmokeReport:
    checks: list[SmokeCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check.ok)

    def render(self) -> str:
        rows = [f"🧪 Smoke-прогон скрипта: {self.passed}/{len(self.checks)} проверок"]
        for check in self.checks:
            mark = "✓" if check.ok else "✗"
            rows.append(f"{mark} {check.name}"
                        + (f" — {check.detail}" if check.detail else ""))
        return "\n".join(rows)


def _load_module(script: Path):
    spec = importlib.util.spec_from_file_location("train_llm_smoke", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def smoke_script(script_path: str | Path, *, dataset_path: str = "",
                 min_rows: int = 1) -> SmokeReport:
    """Run all smoke checks against a generated train_llm.py."""
    report = SmokeReport()
    add = report.checks.append
    script = Path(script_path)

    if not script.is_file():
        add(SmokeCheck("файл скрипта", False, f"не найден: {script}"))
        return report
    add(SmokeCheck("файл скрипта", True, script.name))

    # 1. Compiles under the current interpreter.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(script), cfile=str(Path(tmp) / "s.pyc"),
                               doraise=True)
        add(SmokeCheck("компиляция", True, "синтаксис валиден"))
    except (py_compile.PyCompileError, SyntaxError, OSError) as exc:
        add(SmokeCheck("компиляция", False, str(exc)[:200]))
        return report

    # 2. Imports cleanly (stdlib-only at import time by construction).
    try:
        module = _load_module(script)
        add(SmokeCheck("импорт модуля", True, "зависимости верха файла в порядке"))
    except Exception as exc:
        add(SmokeCheck("импорт модуля", False, f"{type(exc).__name__}: {exc}"[:200]))
        return report

    # 3. Embedded CONFIG is sane.
    config: dict[str, Any] = getattr(module, "CONFIG", {}) or {}
    problems = []
    if config.get("path") not in ("lora", "scratch", "recipe"):
        problems.append(f"path={config.get('path')!r}")
    if not float(config.get("lr", 0) or 0) > 0:
        problems.append("lr<=0")
    if int(config.get("batch", 0) or 0) < 1:
        problems.append("batch<1")
    if int(config.get("epochs", 0) or 0) < 1:
        problems.append("epochs<1")
    add(SmokeCheck("CONFIG скрипта", not problems,
                   "путь/lr/batch/эпохи в норме" if not problems
                   else "; ".join(problems)))

    # 4. The script's own load_texts reads the real dataset.
    dataset = dataset_path or str(config.get("dataset", "") or "")
    if not dataset or not Path(dataset).is_file():
        add(SmokeCheck("загрузка датасета", False,
                       f"датасет не найден: {dataset or '—'}"))
    else:
        try:
            texts = module.load_texts(dataset)
            rows = [t for t in texts if str(t).strip()]
            add(SmokeCheck("загрузка датасета", len(rows) >= min_rows,
                           f"прочитано строк: {len(rows)}"))
        except Exception as exc:
            add(SmokeCheck("загрузка датасета", False,
                           f"{type(exc).__name__}: {exc}"[:200]))

    # 5. log_sample emits a line our own parser reads back (format contract).
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            module.log_sample(7, "smoke-промпт", "smoke-текст",
                              checkpoint="smoke")
        samples = parse_samples(buffer.getvalue())
        good = bool(samples) and samples[0].step == 7 \
            and samples[0].checkpoint == "smoke"
        add(SmokeCheck("формат сэмплов", good,
                       "log_sample → parse_samples: круг замкнулся"
                       if good else "парсер не прочитал сэмпл"))
    except Exception as exc:
        add(SmokeCheck("формат сэмплов", False,
                       f"{type(exc).__name__}: {exc}"[:200]))

    # 6. Training entry points exist for the chosen path.
    needed = ("train_scratch",) if config.get("path") == "scratch" \
        else ("train_lora",)
    missing = [name for name in needed if not callable(getattr(module, name, None))]
    add(SmokeCheck("точка входа обучения", not missing,
                   f"{needed[0]} на месте" if not missing
                   else f"нет функций: {', '.join(missing)}"))
    return report
