"""Chat sessions with the AI mentor: history, persistence, OpenAI payloads."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import app_data_dir


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "tool" | "system"
    content: str = ""
    name: str = ""
    tool_call_id: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_openai(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChatMessage":
        return cls(
            role=str(raw.get("role", "user")),
            content=str(raw.get("content") or ""),
            name=str(raw.get("name", "")),
            tool_call_id=str(raw.get("tool_call_id", "")),
            tool_calls=list(raw.get("tool_calls") or []),
            created_at=float(raw.get("created_at") or time.time()),
        )


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "Новый диалог"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[ChatMessage] = field(default_factory=list)

    def add(self, role: str, content: str = "", **kwargs: Any) -> ChatMessage:
        message = ChatMessage(role=role, content=content, **kwargs)
        self.messages.append(message)
        self.updated_at = time.time()
        if self.title == "Новый диалог" and role == "user" and content.strip():
            head = content.strip().splitlines()[0]
            self.title = (head[:60] + "…") if len(head) > 60 else head
        return message

    def history_for_api(self, system_prompt: str | None = None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(message.to_openai() for message in self.messages)
        return messages

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [asdict(message) for message in self.messages],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChatSession":
        return cls(
            id=str(raw.get("id") or uuid.uuid4().hex[:12]),
            title=str(raw.get("title") or "Новый диалог"),
            created_at=float(raw.get("created_at") or time.time()),
            updated_at=float(raw.get("updated_at") or time.time()),
            messages=[ChatMessage.from_dict(item) for item in raw.get("messages") or []],
        )


class ChatStore:
    """Persists chat sessions as JSON files under the user's app-data folder."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else (app_data_dir() / "chats")
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in "-_")
        if not safe:
            raise ValueError("Invalid session id.")
        return self.directory / f"{safe}.json"

    def save(self, session: ChatSession) -> Path:
        path = self._path(session.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def load(self, session_id: str) -> ChatSession:
        path = self._path(session_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ChatSession.from_dict(raw)

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def list_sessions(self) -> list[ChatSession]:
        sessions: list[ChatSession] = []
        for path in sorted(self.directory.glob("*.json"), reverse=True):
            try:
                sessions.append(self.load(path.stem))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions
