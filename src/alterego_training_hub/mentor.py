"""Explicit API mentor calls for OpenAI-compatible providers."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class MentorError(RuntimeError):
    """A provider configuration or request error safe for display."""


@dataclass(frozen=True)
class MentorReply:
    text: str
    model: str
    usage: dict[str, Any]
    request_id: str | None = None


def chat_endpoint(base_url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(base_url.strip())
    except ValueError:
        raise MentorError("Mentor API URL is invalid.") from None
    if parsed.scheme != "https" or not parsed.hostname:
        raise MentorError("Mentor API must use an absolute HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MentorError("Mentor API URL must not contain credentials, query, or fragment.")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urllib.parse.urlunsplit(("https", parsed.netloc, path, "", ""))


class ApiMentor:
    def __init__(self, base_url: str, model: str, api_key: str, timeout_seconds: float = 60):
        self.endpoint = chat_endpoint(base_url)
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = float(timeout_seconds)
        if not self.model or not self.api_key:
            raise MentorError("Choose a model and store its API key before testing the mentor.")
        if not 1 <= self.timeout_seconds <= 300:
            raise MentorError("Timeout must be between 1 and 300 seconds.")

    def ask(
        self,
        prompt: str,
        *,
        system_prompt: str = (
            "You are a careful AI research mentor. Separate verified facts from "
            "hypotheses, state uncertainty, and recommend measurable tests."
        ),
        max_tokens: int = 700,
        temperature: float = 0.2,
    ) -> MentorReply:
        if not isinstance(prompt, str) or not prompt.strip():
            raise MentorError("Prompt must not be empty.")
        if not 1 <= int(max_tokens) <= 8000:
            raise MentorError("Max response tokens must be between 1 and 8000.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise MentorError("Mentor response exceeded 4 MiB.")
                request_id = response.headers.get("x-request-id")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(2500).decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            detail = detail.replace(self.api_key, "[REDACTED]")[:900]
            raise MentorError(f"Mentor API returned HTTP {exc.code}. {detail}".strip()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MentorError(f"Could not connect to mentor API ({type(exc).__name__}).") from None

        try:
            data = json.loads(raw.decode("utf-8"))
            message = data["choices"][0]["message"]
            text = message.get("content", "")
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "")
                    for part in text
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty response")
        except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            raise MentorError("Mentor API returned an invalid or empty response.") from None

        usage = data.get("usage", {})
        return MentorReply(
            text=text.strip(),
            model=str(data.get("model") or self.model),
            usage=usage if isinstance(usage, dict) else {},
            request_id=request_id,
        )
