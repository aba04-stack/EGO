"""Tests for model export and quantization pipelines (no network, no converters)."""
from __future__ import annotations

import pytest

from alterego_training_hub.exporting import (
    ExportError,
    ExportRequest,
    build_export_command,
    run_export,
    verify_export,
)
from alterego_training_hub.quantize import (
    QuantizeError,
    build_quantize_command,
    estimate_size,
    format_quant_report,
    recipe_info,
    run_quantize,
    size_reduction,
    verify_quantized,
)


class _Done:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_build_export_commands():
    request = ExportRequest(source="org/model", fmt="gguf",
                            output_dir="out", out_type="f16")
    command = build_export_command(request)
    assert command[:2] == ["python", "convert_hf_to_gguf.py"]
    assert "--outtype" in command and "f16" in command

    onnx = build_export_command(ExportRequest(source="org/model", fmt="onnx",
                                              output_dir="out"))
    assert onnx[:3] == ["python", "-m", "transformers.onnx"]

    with pytest.raises(ExportError):
        build_export_command(ExportRequest(source="", fmt="gguf"))
    with pytest.raises(ExportError):
        build_export_command(ExportRequest(source="m", fmt="tensorrt"))
    with pytest.raises(ExportError):
        build_export_command(ExportRequest(source="m", fmt="gguf",
                                           out_type="int4"))


def test_verify_export_gguf_and_onnx(tmp_path):
    checks, artifact = verify_export(tmp_path, "gguf")
    assert artifact is None and any("не найден" in line for line in checks)

    fake = tmp_path / "model.gguf"
    fake.write_bytes(b"not-gguf-magic" + b"\0" * 4096)
    checks, artifact = verify_export(tmp_path, "gguf")
    assert artifact == fake and any("GGUF-магии" in line for line in checks)

    fake.write_bytes(b"GGUF" + b"\0" * 4096)
    checks, artifact = verify_export(tmp_path, "gguf")
    assert not any(line.startswith("✗") for line in checks)

    onnx_dir = tmp_path / "onnx"
    onnx_dir.mkdir()
    (onnx_dir / "model.onnx").write_bytes(b"\x08\x07" + b"\0" * 4096)
    checks, artifact = verify_export(onnx_dir, "onnx")
    assert artifact is not None and any("проверка пройдена" in line
                                        for line in checks)


def test_run_export_with_injectable_runner(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    out_dir = tmp_path / "out"

    def good_runner(command):
        target = out_dir / "gguf"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model.gguf").write_bytes(b"GGUF" + b"\0" * 8192)
        return _Done(0, "converted")

    result = run_export(ExportRequest(source=str(source), fmt="gguf",
                                      output_dir=str(out_dir)),
                        runner=good_runner)
    assert result.ok and result.size_bytes > 0
    assert any("проверка пройдена" in line for line in result.checks)

    result = run_export(ExportRequest(source=str(source), fmt="gguf",
                                      output_dir=str(out_dir)),
                        runner=lambda command: _Done(2, "boom"))
    assert not result.ok and "кодом 2" in result.error

    result = run_export(ExportRequest(source="", fmt="gguf",
                                      output_dir=str(out_dir)))
    assert not result.ok and result.error


def test_quant_recipes_and_sizes():
    assert recipe_info("q4_k_m").family == "gguf"
    assert estimate_size(16_000_000, "q8_0") == int(16_000_000 * 8.5 / 16)
    assert size_reduction(16_000_000, "q4_0") == pytest.approx(16 / 4.5)
    assert "почти без потерь" in format_quant_report("q8_0", 16_000_000)
    with pytest.raises(QuantizeError):
        recipe_info("int4-not-exist")
    with pytest.raises(QuantizeError):
        estimate_size(0, "q8_0")


def test_quantize_commands_verify_and_run(tmp_path):
    command = build_quantize_command("a.gguf", "b.gguf", "q4_k_m")
    assert command[0] == "llama-quantize" and command[1] == "Q4_K_M"
    onnx = build_quantize_command("a.onnx", "b.onnx", "int8")
    assert "onnxruntime.quantization.quantize" in onnx

    src = tmp_path / "model.gguf"
    src.write_bytes(b"GGUF" + b"\0" * 64_000)
    dst = tmp_path / "model.q4.gguf"
    checks = verify_quantized(str(src), str(dst), "q4_k_m")
    assert any("не создана" in line for line in checks)

    dst.write_bytes(b"GGUF" + b"\0" * 10_000)
    checks = verify_quantized(str(src), str(dst), "q4_k_m")
    assert any("сжатие" in line for line in checks)

    def good_runner(command):
        dst.write_bytes(b"GGUF" + b"\0" * 10_000)
        return _Done(0, "quantized")

    result = run_quantize(str(src), str(dst), "q4_k_m", runner=good_runner)
    assert result.ok and not result.error

    result = run_quantize(str(src), str(dst), "q4_k_m",
                          runner=lambda command: _Done(1, "bad"))
    assert not result.ok and "кодом 1" in result.error
