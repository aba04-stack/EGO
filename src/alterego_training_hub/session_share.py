"""Session sharing: export/import chat sessions as Markdown, HTML or JSON."""
from __future__ import annotations

import html
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .chat import ChatSession

ROLE_LABELS = {"user": "Вы", "assistant": "Ассистент", "tool": "Инструмент",
               "system": "Система"}


class ShareError(RuntimeError):
    """Share input error safe to display."""


@dataclass
class ExportedSession:
    path: str
    fmt: str
    messages: int


def session_to_markdown(session: ChatSession) -> str:
    stamp = time.strftime("%d.%m.%Y %H:%M",
                          time.localtime(session.created_at or time.time()))
    lines = [f"# Диалог: {session.title}", "", f"_Экспортировано: {stamp}_", ""]
    for message in session.messages:
        if message.role == "tool":
            continue
        when = time.strftime("%H:%M", time.localtime(message.created_at))
        label = ROLE_LABELS.get(message.role, message.role)
        content = str(message.content or "").strip()
        if not content:
            continue
        lines += [f"**{label}** · {when}", "", content, ""]
    return "\n".join(lines)


def session_to_html(session: ChatSession) -> str:
    """Standalone shareable HTML file (no external assets)."""
    rows = []
    for message in session.messages:
        if message.role == "tool" or not str(message.content or "").strip():
            continue
        when = time.strftime("%H:%M", time.localtime(message.created_at))
        label = ROLE_LABELS.get(message.role, message.role)
        cls = "user" if message.role == "user" else "bot"
        rows.append(
            f"<div class=\"msg {cls}\"><span class=\"who\">"
            f"{html.escape(label)} · {when}</span>"
            f"<div class=\"body\">{html.escape(str(message.content))}</div></div>")
    title = html.escape(session.title)
    return (
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title><style>"
        "body{font-family:'Segoe UI',Arial,sans-serif;max-width:760px;"
        "margin:24px auto;padding:0 16px;background:#f9fafb;color:#111827}"
        ".msg{background:#fff;border:1px solid #e5e7eb;border-radius:10px;"
        "padding:10px 14px;margin:10px 0}"
        ".msg.user{border-color:#93c5fd}.who{color:#6b7280;font-size:12px}"
        ".body{white-space:pre-wrap;margin-top:4px}"
        "</style></head><body>"
        f"<h1>Диалог: {title}</h1>" + "\n".join(rows) + "</body></html>")


def session_to_json(session: ChatSession) -> str:
    return json.dumps({"kind": "alterego-chat-session", "version": 1,
                       "session": session.to_dict()},
                      ensure_ascii=False, indent=2)


def session_from_json(text: str) -> ChatSession:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ShareError(f"Некорректный JSON сессии: {exc}") from None
    payload = raw.get("session") if isinstance(raw, dict) and \
        raw.get("kind") == "alterego-chat-session" else raw
    if not isinstance(payload, dict):
        raise ShareError("В файле нет данных сессии.")
    try:
        return ChatSession.from_dict(payload)
    except (TypeError, ValueError, KeyError) as exc:
        raise ShareError(f"Не удалось разобрать сессию: {exc}") from None


def export_session(session: ChatSession, path: str | Path, *,
                   fmt: str = "md") -> ExportedSession:
    file = Path(path)
    fmt = str(fmt or "").lower()
    file.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        file = file.with_suffix(".md")
        file.write_text(session_to_markdown(session), encoding="utf-8")
    elif fmt == "html":
        file = file.with_suffix(".html")
        file.write_text(session_to_html(session), encoding="utf-8")
    elif fmt == "json":
        file = file.with_suffix(".json")
        file.write_text(session_to_json(session), encoding="utf-8")
    else:
        raise ShareError(f"Формат сессии: md, html или json (получен «{fmt}»).")
    return ExportedSession(str(file), fmt, len(session.messages))


def import_session(path: str | Path) -> ChatSession:
    file = Path(path)
    if not file.is_file():
        raise ShareError(f"Файл не найден: {file}")
    return session_from_json(file.read_text(encoding="utf-8"))
