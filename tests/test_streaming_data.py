"""v1.8.3: streaming dataset ops — no full-file materialisation."""
from __future__ import annotations

import json

from alterego_training_hub.data_audit import audit_rows
from alterego_training_hub.datasets import iter_rows, read_rows, write_rows_iter
from alterego_training_hub.sft_data import (
    decontaminate,
    decontaminate_file,
    dedupe_near,
    dedupe_near_file,
    validate_sft,
)

ROWS = [
    {"text": "кошки любят спать на тёплом подоконнике дома"},
    {"text": "кошки любят спать на тёплом подоконнике дома"},  # exact dup
    {"text": "кошки любят спать на тёплом подоконнике всегда"},  # near dup
    {"text": "собаки любят гулять в парке с хозяином утром"},
    {"text": "птицы поют весной громко и радостно в лесу"},
]


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def test_iter_rows_matches_read_rows(tmp_path):
    path = tmp_path / "d.jsonl"
    _write_jsonl(path, ROWS)
    assert list(iter_rows(path, "jsonl")) == read_rows(path, "jsonl")
    txt = tmp_path / "d.txt"
    txt.write_text("раз\nдва\n\nтри\n", encoding="utf-8")
    assert [r["text"] for r in iter_rows(txt, "txt")] == ["раз", "два", "три"]


def test_write_rows_iter_roundtrip(tmp_path):
    out = tmp_path / "out.jsonl"
    assert write_rows_iter(out, iter(ROWS), "jsonl") == len(ROWS)
    assert read_rows(out, "jsonl") == ROWS
    out_csv = tmp_path / "out.csv"
    assert write_rows_iter(out_csv, iter(ROWS), "csv") == len(ROWS)
    assert read_rows(out_csv, "csv")[0]["text"] == ROWS[0]["text"]


def test_audit_and_validate_accept_iterators(tmp_path):
    path = tmp_path / "d.jsonl"
    _write_jsonl(path, ROWS)
    streamed = audit_rows(iter_rows(path, "jsonl"))
    listed = audit_rows(ROWS)
    assert (streamed.rows, streamed.duplicates, streamed.chars) == \
        (listed.rows, listed.duplicates, listed.chars)
    progress = []
    audit_rows(iter_rows(path, "jsonl"), progress=progress.append)
    report = validate_sft(iter(ROWS))  # generator, не список
    assert report.rows == len(ROWS)


def test_dedupe_near_file_matches_in_memory(tmp_path):
    src = tmp_path / "d.jsonl"
    dst = tmp_path / "d.dedup.jsonl"
    _write_jsonl(src, ROWS)
    kept_mem, removed_mem = dedupe_near(ROWS, threshold=0.6)
    result = dedupe_near_file(src, dst, "jsonl", threshold=0.6)
    assert result.removed == removed_mem and result.kept == len(kept_mem)
    assert read_rows(dst, "jsonl") == kept_mem


def test_decontaminate_file_matches_in_memory(tmp_path):
    train = tmp_path / "train.jsonl"
    evalf = tmp_path / "eval.jsonl"
    dst = tmp_path / "clean.jsonl"
    eval_rows = [{"text": "собаки любят гулять в парке с хозяином утром"}]
    _write_jsonl(train, ROWS)
    _write_jsonl(evalf, eval_rows)
    mem = decontaminate(ROWS, eval_rows, threshold=0.8)
    result = decontaminate_file(train, evalf, dst, "jsonl", threshold=0.8)
    assert result.contaminated == mem.contaminated
    assert read_rows(dst, "jsonl") == mem.cleaned


def test_streaming_big_file(tmp_path):
    src = tmp_path / "big.jsonl"
    total = 30_000
    with src.open("w", encoding="utf-8") as handle:
        for i in range(total):
            row = {"text": f"уникальная строка номер {i} про обучение моделей"}
            if i % 10_000 == 0 and i:
                row = {"text": "уникальная строка номер 0 про обучение моделей"}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    assert audit_rows(iter_rows(src, "jsonl")).rows == total
    dst = tmp_path / "big.dedup.jsonl"
    result = dedupe_near_file(src, dst, "jsonl", threshold=0.99)
    assert result.kept == total - 2 and result.removed == 2
