"""Full training report export: Markdown and print-ready single-file HTML.

The report assembles everything the hub knows: model info, metrics, eval
verdict, watchdog issues, comparison, agent plan and recent activity.
PDF is produced through the browser print dialog from the HTML (or reportlab
when installed) — the core stays dependency-free.
"""
from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from pathlib import Path


class ReportExportError(RuntimeError):
    """Export input error safe to display."""


@dataclass
class ReportContext:
    """Everything needed to render a report; fill only what exists."""
    title: str = "Отчёт по обучению"
    model_info: dict = field(default_factory=dict)
    metrics_lines: list[str] = field(default_factory=list)
    eval_lines: list[str] = field(default_factory=list)
    watchdog_lines: list[str] = field(default_factory=list)
    comparison_lines: list[str] = field(default_factory=list)
    plan_tasks: list[dict] = field(default_factory=list)
    activity_lines: list[str] = field(default_factory=list)
    assessment_lines: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


def build_markdown_report(context: ReportContext) -> str:
    stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(context.created_at))
    lines = [f"# {context.title}", "", f"_Сформировано: {stamp}_", ""]
    if context.model_info:
        lines += ["## Модель", ""]
        for key, value in context.model_info.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")
    for heading, items in (
            ("Метрики обучения", context.metrics_lines),
            ("Валидация", context.eval_lines),
            ("Контроль качества (watchdog)", context.watchdog_lines),
            ("Сравнение запусков", context.comparison_lines),
            ("Оценка наставника", context.assessment_lines)):
        if items:
            lines += [f"## {heading}", ""]
            lines += [str(item) for item in items]
            lines.append("")
    if context.plan_tasks:
        marks = {"done": "x", "failed": "!", "in_progress": "~", "pending": " "}
        lines += ["## План агента", ""]
        for task in context.plan_tasks:
            mark = marks.get(str(task.get("status", "pending")), " ")
            lines.append(f"- [{mark}] {task.get('title', '')}")
        lines.append("")
    if context.activity_lines:
        lines += ["## Журнал действий (последние события)", ""]
        lines += [f"- {item}" for item in context.activity_lines]
        lines.append("")
    return "\n".join(lines)


_MD_HEADINGS = (("### ", "h3"), ("## ", "h2"), ("# ", "h1"))


def markdown_to_html(markdown: str, title: str = "Отчёт") -> str:
    """Minimal, safe Markdown→HTML for the printable single-file report."""
    body: list[str] = []
    in_list = False
    for raw in str(markdown or "").splitlines():
        line = html.escape(raw)
        if not line.strip():
            if in_list:
                body.append("</ul>")
                in_list = False
            continue
        matched = False
        for prefix, tag in _MD_HEADINGS:
            if line.startswith(prefix):
                body.append(f"<{tag}>{line[len(prefix):].strip()}</{tag}>")
                matched = True
                break
        if matched:
            continue
        if line.startswith("- ["):
            if not in_list:
                body.append("<ul class=\"tasks\">")
                in_list = True
            checked = "☑" if line[3:4] == "x" else ("☒" if line[3:4] == "!" else "☐")
            body.append(f"<li>{checked} {line[6:] if len(line) > 6 else ''}</li>")
            continue
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        body.append(f"<p>{_inline(line)}</p>")
    if in_list:
        body.append("</ul>")
    return (
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "<style>"
        "body{font-family:'Segoe UI',Arial,sans-serif;max-width:860px;"
        "margin:24px auto;padding:0 16px;color:#1f2937;line-height:1.5}"
        "h1{border-bottom:2px solid #2a7}h2{border-bottom:1px solid #ddd;"
        "margin-top:28px}ul.tasks{list-style:none;padding-left:0}"
        "code{background:#f3f4f6;padding:1px 5px;border-radius:4px}"
        "@media print{body{margin:0}}.stamp{color:#6b7280;font-size:13px}"
        "</style></head><body>"
        + "\n".join(body) +
        "</body></html>")


def _inline(text: str) -> str:
    out = text
    for marker in ("**", "__"):
        out = out.replace(marker, "")
    out = out.replace("_", "‗")  # avoid fake emphasis in plain text
    return out


@dataclass
class ExportedReport:
    path: str
    fmt: str
    note: str = ""


def save_report(path: str | Path, context: ReportContext, *,
                fmt: str = "md") -> ExportedReport:
    """Write the report as Markdown or HTML (PDF via browser print)."""
    file = Path(path)
    fmt = str(fmt or "").lower()
    markdown = build_markdown_report(context)
    file.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        file = file.with_suffix(".md")
        file.write_text(markdown, encoding="utf-8")
        return ExportedReport(str(file), "md")
    if fmt in {"html", "pdf"}:
        file = file.with_suffix(".html" if fmt == "html" else ".html")
        file.write_text(markdown_to_html(markdown, context.title),
                        encoding="utf-8")
        note = ("HTML готов: распечатайте в PDF через браузер (Ctrl+P)."
                if fmt == "pdf" else "")
        return ExportedReport(str(file), fmt, note)
    raise ReportExportError(f"Формат отчёта: md, html или pdf (получен «{fmt}»).")
