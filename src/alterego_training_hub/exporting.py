"""Model export pipeline: ONNX / GGUF conversion commands, checks, runner.

Heavy conversions run as external tools (transformers.onnx, llama.cpp
converters); this module builds the exact commands, verifies the produced
artifacts and returns a Russian report. No third-party imports here.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

EXPORT_FORMATS: dict[str, dict] = {
    "onnx": {
        "label": "ONNX (для кроссплатформенного инференса)",
        "suffix": ".onnx",
        "tool_hint": "pip install 'transformers[onnx]' optimum",
    },
    "gguf": {
        "label": "GGUF (для llama.cpp / Ollama)",
        "suffix": ".gguf",
        "tool_hint": "нужен репозиторий llama.cpp (convert_hf_to_gguf.py)",
    },
}
GGUF_MAGIC = b"GGUF"
MIN_ARTIFACT_BYTES = 1024


class ExportError(RuntimeError):
    """Export input error safe to display."""


@dataclass
class ExportRequest:
    source: str                    # HF model id or local folder
    fmt: str = "gguf"
    output_dir: str = ""
    out_type: str = "f16"          # gguf outtype (f32/f16/q8_0...)
    timeout_seconds: float = 600.0


@dataclass
class ExportResult:
    ok: bool
    fmt: str
    command: list[str] = field(default_factory=list)
    output_path: str = ""
    size_bytes: int = 0
    checks: list[str] = field(default_factory=list)
    log_tail: str = ""
    error: str = ""
    duration_s: float = 0.0


def build_export_command(request: ExportRequest) -> list[str]:
    """Exact conversion command for the requested format."""
    fmt = str(request.fmt or "").lower()
    source = str(request.source or "").strip()
    if not source:
        raise ExportError("Укажите источник модели (папку или id на HF).")
    if fmt not in EXPORT_FORMATS:
        raise ExportError(f"Формат экспорта: один из {sorted(EXPORT_FORMATS)}.")
    out_dir = Path(request.output_dir or "exports") / fmt
    if fmt == "onnx":
        return ["python", "-m", "transformers.onnx", "--model", source,
                str(out_dir)]
    out_file = out_dir / f"{Path(source).name or 'model'}.gguf"
    out_type = request.out_type or "f16"
    if out_type not in {"f32", "f16", "bf16", "q8_0"}:
        raise ExportError("out_type: f32, f16, bf16 или q8_0.")
    return ["python", "convert_hf_to_gguf.py", source, "--outfile", str(out_file),
            "--outtype", out_type]


def _protobuf_fields(data: bytes) -> list[int] | None:
    """Номера полей верхнего уровня protobuf или None при битом потоке."""
    fields: list[int] = []
    pos = 0
    while pos < len(data):
        # varint-тег
        tag, shift = 0, 0
        while True:
            if pos >= len(data) or shift > 63:
                return None
            byte = data[pos]
            pos += 1
            tag |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        number, wire = tag >> 3, tag & 7
        if number == 0:
            return None
        fields.append(number)
        if wire == 0:  # varint
            while pos < len(data) and data[pos] & 0x80:
                pos += 1
            pos += 1
        elif wire == 1:
            pos += 8
        elif wire == 2:  # length-delimited
            length, shift = 0, 0
            while True:
                if pos >= len(data) or shift > 63:
                    return None
                byte = data[pos]
                pos += 1
                length |= (byte & 0x7F) << shift
                if not byte & 0x80:
                    break
                shift += 7
            pos += length
        elif wire == 5:
            pos += 4
        else:
            return None
        if pos > len(data):
            return None
    return fields


def _check_onnx_structure(artifact: Path) -> str | None:
    """Структурная проверка ONNX (protobuf ModelProto), не только расширение."""
    try:
        import onnx  # type: ignore

        model = onnx.load(str(artifact))
        onnx.checker.check_model(model)
        return None
    except ImportError:
        pass
    except Exception as exc:
        return f"onnx.checker: {exc}"
    fields = _protobuf_fields(artifact.read_bytes())
    if fields is None:
        return "файл не является корректным protobuf-потоком"
    # ModelProto: 1=ir_version, 7=graph должны присутствовать
    if 7 not in fields:
        return "в protobuf нет поля graph (7) — это не модель ONNX"
    return None


def _check_gguf_header(artifact: Path) -> str | None:
    import struct

    with artifact.open("rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:4] != GGUF_MAGIC:
        return "нет GGUF-магии"
    version, n_tensors, n_meta = struct.unpack("<IQQ", head[4:24])
    if version not in (2, 3) or n_tensors > 100_000 or n_meta > 100_000:
        return (f"подозрительный заголовок GGUF: version={version}, "
                f"tensors={n_tensors}, meta={n_meta}")
    return None


def verify_export(output_dir: str | Path, fmt: str, *,
                  since: float | None = None) -> tuple[list[str], Path | None]:
    """Check the produced artifact: существование, свежесть, структура.

    ``since`` (момент запуска конвертации) отсекает СТАРЫЕ файлы в папке:
    успех засчитывается только артефакту этого запуска.
    """
    fmt = str(fmt or "").lower()
    if fmt not in EXPORT_FORMATS:
        raise ExportError(f"Неизвестный формат: {fmt}")
    base = Path(output_dir)
    checks: list[str] = []
    if fmt == "gguf":
        candidates = sorted(base.rglob("*.gguf")) if base.is_dir() else []
    else:
        candidates = sorted(base.rglob("*.onnx")) if base.is_dir() else []
    if since is not None:
        fresh = [c for c in candidates if c.stat().st_mtime >= since - 1.0]
        if candidates and not fresh:
            checks.append("✗ в папке есть только СТАРЫЕ артефакты — этот "
                          "запуск ничего не создал (не выдаём прошлое за результат)")
            return checks, None
        candidates = fresh
    if not candidates:
        checks.append("✗ артефакт не найден: конвертация не выполнена "
                      f"(проверьте инструменты: {EXPORT_FORMATS[fmt]['tool_hint']})")
        return checks, None
    artifact = max(candidates, key=lambda c: c.stat().st_mtime)
    size = artifact.stat().st_size
    checks.append(f"✓ файл: {artifact.name} ({size / 1_048_576:.1f} MB)")
    if size < MIN_ARTIFACT_BYTES:
        checks.append("✗ файл подозрительно мал — конвертация оборвана")
        return checks, artifact
    if fmt == "gguf":
        problem = _check_gguf_header(artifact)
        if problem is None:
            checks.append("✓ заголовок GGUF валиден (магия, версия, счётчики)")
        else:
            checks.append(f"✗ GGUF: {problem}")
            return checks, artifact
    else:
        problem = _check_onnx_structure(artifact)
        if problem is None:
            checks.append("✓ структура ONNX подтверждена (protobuf ModelProto)")
        else:
            checks.append(f"✗ ONNX: {problem}")
            return checks, artifact
    checks.append("✓ проверка пройдена")
    return checks, artifact


def run_export(request: ExportRequest, *,
               runner=None) -> ExportResult:
    """Execute the conversion command and verify the artifact.

    ``runner`` is injectable for tests (defaults to subprocess.run).
    """
    started = time.monotonic()
    started_wall = time.time()
    try:
        command = build_export_command(request)
    except ExportError as exc:
        return ExportResult(ok=False, fmt=request.fmt, error=str(exc))

    out_dir = Path(request.output_dir or "exports") / request.fmt
    out_dir.mkdir(parents=True, exist_ok=True)
    log_tail = ""
    try:
        if runner is not None:
            completed = runner(command)
            returncode = getattr(completed, "returncode", 0)
            log_tail = str(getattr(completed, "stdout", "") or "")[-2000:]
        else:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                timeout=max(30.0, float(request.timeout_seconds)))
            returncode = completed.returncode
            log_tail = ((completed.stdout or "") + "\n" + (completed.stderr or ""))[-2000:]
    except FileNotFoundError:
        return ExportResult(
            ok=False, fmt=request.fmt, command=command,
            error=f"Инструмент не найден: {command[0]}. "
                  f"{EXPORT_FORMATS[request.fmt]['tool_hint']}")
    except subprocess.TimeoutExpired:
        return ExportResult(ok=False, fmt=request.fmt, command=command,
                            error="Конвертация превысила таймаут.")
    if returncode != 0:
        return ExportResult(ok=False, fmt=request.fmt, command=command,
                            log_tail=log_tail,
                            error=f"Конвертация завершилась с кодом {returncode}.")

    checks, artifact = verify_export(out_dir, request.fmt,
                                     since=started_wall)
    ok = artifact is not None and artifact.stat().st_size >= MIN_ARTIFACT_BYTES \
        and not any(line.startswith("✗") for line in checks)
    return ExportResult(
        ok=ok, fmt=request.fmt, command=command,
        output_path=str(artifact or ""), size_bytes=artifact.stat().st_size
        if artifact else 0,
        checks=checks, log_tail=log_tail,
        duration_s=time.monotonic() - started,
        error="" if ok else "Проверка экспорта не пройдена.")
