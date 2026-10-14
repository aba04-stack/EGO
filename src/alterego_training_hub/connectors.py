"""Developer connectors: GitHub, Hugging Face, Gmail.

Secrets (tokens, app passwords) live only in the OS credential store. The
mentor agent can call connectors through tools: search GitHub repositories,
search Hugging Face models, and send notification e-mail (with confirmation).
"""
from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any

from .config import SecretStore


class ConnectorError(RuntimeError):
    """Connector configuration or request error safe to display."""


@dataclass(frozen=True)
class ConnectorSpec:
    id: str
    title: str
    description: str
    secret_label: str
    fields: tuple[tuple[str, str], ...] = ()


CONNECTORS: tuple[ConnectorSpec, ...] = (
    ConnectorSpec(
        id="github",
        title="GitHub",
        description="Поиск репозиториев через GitHub API. Токен — в системном "
                    "хранилище; клонирование идёт через Git Credential Manager.",
        secret_label="Personal access token (необязательно, для приватных API)",
    ),
    ConnectorSpec(
        id="huggingface",
        title="Hugging Face",
        description="Поиск моделей и карточки моделей на Hugging Face Hub. "
                    "Токен нужен только для приватных/гейтнутых моделей.",
        secret_label="HF token (необязательно)",
    ),
    ConnectorSpec(
        id="gmail",
        title="Gmail (SMTP)",
        description="Отправка уведомлений на почту (например, об окончании "
                    "обучения). Используйте App Password при 2FA.",
        secret_label="App Password",
    ),
)

_SECRET_KEYS = {
    "github": "connector.github_token",
    "huggingface": "connector.hf_token",
    "gmail": "connector.gmail_app_password",
}

HTTP_TIMEOUT = 20.0
_MAX_RESPONSE = 2 * 1024 * 1024


def _http_json(url: str, *, token: str = "", accept: str = "application/json") -> Any:
    headers = {"Accept": accept, "User-Agent": "AlterEgo-Training-Hub"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            raw = response.read(_MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        raise ConnectorError(f"HTTP {exc.code} от сервиса.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectorError(f"Нет соединения ({type(exc).__name__}).") from None
    if len(raw) > _MAX_RESPONSE:
        raise ConnectorError("Ответ сервиса слишком большой.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ConnectorError("Сервис вернул некорректный JSON.") from None


class ConnectorManager:
    """Status + actions for every registered connector."""

    def __init__(self, secrets: SecretStore | None = None,
                 *, gmail_from: str = "", smtp_host: str = "smtp.gmail.com",
                 smtp_port: int = 587):
        self.secrets = secrets or SecretStore()
        self.gmail_from = gmail_from.strip()
        self.smtp_host = smtp_host
        self.smtp_port = int(smtp_port)

    # -- registry --------------------------------------------------------
    def specs(self) -> tuple[ConnectorSpec, ...]:
        return CONNECTORS

    def secret_key(self, connector_id: str) -> str:
        try:
            return _SECRET_KEYS[connector_id]
        except KeyError:
            raise ConnectorError(f"Неизвестный коннектор: {connector_id}") from None

    def status(self, connector_id: str) -> dict[str, Any]:
        spec = next((item for item in CONNECTORS if item.id == connector_id), None)
        if spec is None:
            raise ConnectorError(f"Неизвестный коннектор: {connector_id}")
        try:
            saved = bool(self.secrets.get(self.secret_key(connector_id)))
        except RuntimeError:
            saved = False
        optional = connector_id in {"github", "huggingface"}
        return {
            "id": spec.id,
            "title": spec.title,
            "description": spec.description,
            "secret_label": spec.secret_label,
            "connected": saved,
            "optional": optional,
            "state": "подключено" if saved else ("токен не требуется" if optional
                                                 else "не настроено"),
        }

    def set_secret(self, connector_id: str, value: str) -> None:
        self.secrets.set(self.secret_key(connector_id), value)

    def delete_secret(self, connector_id: str) -> None:
        self.secrets.delete(self.secret_key(connector_id))

    def _token(self, connector_id: str) -> str:
        try:
            return self.secrets.get(self.secret_key(connector_id))
        except RuntimeError:
            return ""

    # -- GitHub ----------------------------------------------------------
    def github_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = str(query).strip()
        if not query:
            raise ConnectorError("Запрос не должен быть пустым.")
        limit = max(1, min(int(limit), 10))
        url = ("https://api.github.com/search/repositories?q="
               + urllib.parse.quote(query) + f"&per_page={limit}")
        data = _http_json(url, token=self._token("github"),
                          accept="application/vnd.github+json")
        items = data.get("items") if isinstance(data, dict) else None
        results = []
        for item in (items or [])[:limit]:
            if isinstance(item, dict):
                results.append({
                    "full_name": item.get("full_name", ""),
                    "url": item.get("html_url", ""),
                    "stars": item.get("stargazers_count", 0),
                    "description": (item.get("description") or "")[:200],
                    "clone_url": item.get("clone_url", ""),
                })
        return results

    # -- Hugging Face ----------------------------------------------------
    def huggingface_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = str(query).strip()
        if not query:
            raise ConnectorError("Запрос не должен быть пустым.")
        limit = max(1, min(int(limit), 10))
        url = ("https://huggingface.co/api/models?search="
               + urllib.parse.quote(query) + f"&limit={limit}")
        data = _http_json(url, token=self._token("huggingface"))
        results = []
        for item in (data if isinstance(data, list) else [])[:limit]:
            if isinstance(item, dict):
                results.append({
                    "id": item.get("id", ""),
                    "downloads": item.get("downloads", 0),
                    "likes": item.get("likes", 0),
                    "pipeline_tag": item.get("pipeline_tag", ""),
                })
        return results

    def huggingface_model(self, model_id: str) -> dict[str, Any]:
        model_id = str(model_id).strip()
        if not model_id or any(ch.isspace() for ch in model_id):
            raise ConnectorError("Укажите ID модели вида org/name.")
        url = "https://huggingface.co/api/models/" + urllib.parse.quote(model_id,
                                                                        safe="/")
        data = _http_json(url, token=self._token("huggingface"))
        if not isinstance(data, dict):
            raise ConnectorError("Карточка модели не найдена.")
        return {
            "id": data.get("id", model_id),
            "downloads": data.get("downloads", 0),
            "likes": data.get("likes", 0),
            "tags": (data.get("tags") or [])[:12],
            "library_name": data.get("library_name", ""),
        }

    # -- Gmail -----------------------------------------------------------
    def gmail_send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        to = str(to).strip()
        if "@" not in to or any(ch.isspace() for ch in to):
            raise ConnectorError("Некорректный адрес получателя.")
        if not str(subject).strip():
            raise ConnectorError("Тема письма не должна быть пустой.")
        password = self._token("gmail")
        if not password or not self.gmail_from:
            raise ConnectorError(
                "Настройте адрес отправителя и App Password коннектора Gmail.")
        message = MIMEText(str(body), "plain", "utf-8")
        message["From"] = self.gmail_from
        message["To"] = to
        message["Subject"] = str(subject)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as client:
                client.starttls()
                client.login(self.gmail_from, password)
                client.sendmail(self.gmail_from, [to], message.as_string())
        except smtplib.SMTPAuthenticationError:
            raise ConnectorError("Gmail отклонил логин — проверьте App Password.") from None
        except (smtplib.SMTPException, OSError) as exc:
            raise ConnectorError(f"Не удалось отправить письмо ({type(exc).__name__}).") from None
        return {"ok": True, "to": to, "subject": subject}

    # -- agent tool bridge ----------------------------------------------
    def agent_tools(self) -> tuple[dict[str, Any], list[dict[str, Any]], frozenset[str]]:
        """Return (handlers, schemas, mutation tool names) for MentorAgent."""
        def search_github(args):
            return {"ok": True, "results": self.github_search(
                args.get("query", ""), int(args.get("limit", 5) or 5))}

        def search_huggingface(args):
            return {"ok": True, "results": self.huggingface_search(
                args.get("query", ""), int(args.get("limit", 5) or 5))}

        def huggingface_model_card(args):
            return {"ok": True, "model": self.huggingface_model(args.get("model_id", ""))}

        def send_email(args):
            result = self.gmail_send(args.get("to", ""), args.get("subject", ""),
                                     args.get("body", ""))
            return {"ok": True, **result}

        handlers = {
            "search_github": search_github,
            "search_huggingface": search_huggingface,
            "huggingface_model_card": huggingface_model_card,
            "send_email": send_email,
        }
        schemas = [
            {"type": "function", "function": {
                "name": "search_github",
                "description": "Поиск репозиториев на GitHub.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5}},
                    "required": ["query"]}}},
            {"type": "function", "function": {
                "name": "search_huggingface",
                "description": "Поиск моделей на Hugging Face Hub.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5}},
                    "required": ["query"]}}},
            {"type": "function", "function": {
                "name": "huggingface_model_card",
                "description": "Карточка модели Hugging Face (org/name).",
                "parameters": {"type": "object", "properties": {
                    "model_id": {"type": "string"}},
                    "required": ["model_id"]}}},
            {"type": "function", "function": {
                "name": "send_email",
                "description": "Отправить уведомление на почту (требует подтверждения).",
                "parameters": {"type": "object", "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"}},
                    "required": ["to", "subject", "body"]}}},
        ]
        return handlers, schemas, frozenset({"send_email"})
