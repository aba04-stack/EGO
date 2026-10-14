"""Tests for report export and session sharing."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.chat import ChatSession
from alterego_training_hub.report_export import (
    ReportContext,
    ReportExportError,
    build_markdown_report,
    markdown_to_html,
    save_report,
)
from alterego_training_hub.session_share import (
    ShareError,
    export_session,
    import_session,
    session_from_json,
    session_to_html,
    session_to_json,
    session_to_markdown,
)


def _context() -> ReportContext:
    return ReportContext(
        title="Отчёт по обучению",
        model_info={"Модель": "demo", "Тип": "local"},
        metrics_lines=["- loss: 0.5"],
        eval_lines=["Лучшая эпоха: 3"],
        watchdog_lines=["⚠ что-то"],
        plan_tasks=[{"title": "шаг 1", "status": "done"},
                    {"title": "шаг 2", "status": "pending"}],
        activity_lines=["training: запуск"],
    )


def test_build_markdown_report_sections():
    text = build_markdown_report(_context())
    assert text.startswith("# Отчёт по обучению")
    for heading in ("## Модель", "## Метрики обучения", "## Валидация",
                    "## Контроль качества (watchdog)", "## План агента",
                    "## Журнал действий"):
        assert heading in text
    assert "- [x] шаг 1" in text and "- [ ] шаг 2" in text
    assert "- **Модель**: demo" in text


def test_markdown_to_html_escapes_and_structures():
    html = markdown_to_html("# Заголовок\n\n- пункт\n- [x] задача\n\nтекст "
                            "<script>alert(1)</script>")
    assert "<h1>Заголовок</h1>" in html
    assert "<li>пункт</li>" in html
    assert "☑" in html and "задача" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "@media print" in html  # print-ready for PDF via browser


def test_save_report_formats(tmp_path):
    exported = save_report(tmp_path / "report", _context(), fmt="md")
    assert exported.path.endswith(".md")
    assert (tmp_path / "report.md").exists()

    exported = save_report(tmp_path / "report", _context(), fmt="html")
    assert exported.path.endswith(".html")

    exported = save_report(tmp_path / "report", _context(), fmt="pdf")
    assert exported.path.endswith(".html") and "Ctrl+P" in exported.note

    with pytest.raises(ReportExportError):
        save_report(tmp_path / "x", _context(), fmt="docx")


def _session() -> ChatSession:
    session = ChatSession(title="Тест")
    session.add("user", "Привет")
    session.add("assistant", "Здравствуйте!")
    session.add("tool", "скрыто", name="read_file")
    session.add("user", "Пока")
    return session


def test_session_markdown_and_html():
    session = _session()
    markdown = session_to_markdown(session)
    assert "# Диалог: Тест" in markdown
    assert "**Вы**" in markdown and "**Ассистент**" in markdown
    assert "скрыто" not in markdown  # tool messages hidden
    html = session_to_html(session)
    assert "Здравствуйте!" in html and "msg user" in html


def test_session_json_roundtrip_and_files(tmp_path):
    session = _session()
    restored = session_from_json(session_to_json(session))
    assert restored.title == "Тест"
    assert [m.role for m in restored.messages] == \
           [m.role for m in session.messages]
    assert restored.messages[1].content == "Здравствуйте!"

    exported = export_session(session, tmp_path / "s", fmt="json")
    assert exported.messages == 4
    imported = import_session(exported.path)
    assert imported.title == "Тест"

    exported = export_session(session, tmp_path / "s", fmt="md")
    assert (tmp_path / "s.md").exists()
    exported = export_session(session, tmp_path / "s", fmt="html")
    assert (tmp_path / "s.html").exists()

    with pytest.raises(ShareError):
        export_session(session, tmp_path / "s", fmt="pdf")
    with pytest.raises(ShareError):
        import_session(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("не json", encoding="utf-8")
    with pytest.raises(ShareError):
        import_session(bad)
    bad.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(ShareError):
        import_session(bad)
