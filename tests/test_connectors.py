import json
import smtplib

import pytest

from alterego_training_hub.config import SecretStore
from alterego_training_hub.connectors import ConnectorError, ConnectorManager


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return json.dumps(self._payload).encode("utf-8")


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    values = {}
    import keyring
    monkeypatch.setattr(keyring, "set_password",
                        lambda s, n, v: values.__setitem__((s, n), v))
    monkeypatch.setattr(keyring, "get_password",
                        lambda s, n: values.get((s, n)))
    monkeypatch.setattr(keyring, "delete_password",
                        lambda s, n: values.pop((s, n), None))
    return ConnectorManager(SecretStore(service="test-connectors"),
                            gmail_from="me@gmail.com")


def test_specs_and_status(manager):
    specs = manager.specs()
    assert [spec.id for spec in specs] == ["github", "huggingface", "gmail"]
    github = manager.status("github")
    assert github["connected"] is False and github["optional"] is True
    manager.set_secret("github", "ghp_test")
    assert manager.status("github")["connected"] is True
    manager.delete_secret("github")
    assert manager.status("github")["connected"] is False
    with pytest.raises(ConnectorError):
        manager.status("jira")
    with pytest.raises(ConnectorError):
        manager.set_secret("jira", "x")


def test_github_search(monkeypatch, manager):
    def fake_urlopen(request, timeout):
        assert request.full_url.startswith("https://api.github.com/search/repositories")
        assert request.get_header("Accept") == "application/vnd.github+json"
        return FakeResponse({"items": [{
            "full_name": "aba04-stack/-",
            "html_url": "https://github.com/aba04-stack/-",
            "stargazers_count": 5,
            "description": "LLM studio",
            "clone_url": "https://github.com/aba04-stack/-.git",
        }]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    results = manager.github_search("llm studio", limit=3)
    assert results[0]["full_name"] == "aba04-stack/-"
    assert results[0]["stars"] == 5
    with pytest.raises(ConnectorError):
        manager.github_search("  ")


def test_huggingface_search_and_card(monkeypatch, manager):
    def fake_urlopen(request, timeout):
        if "/api/models?" in request.full_url:
            return FakeResponse([
                {"id": "org/tiny-model", "downloads": 100, "likes": 4,
                 "pipeline_tag": "text-generation"},
            ])
        return FakeResponse({"id": "org/tiny-model", "downloads": 100, "likes": 4,
                             "tags": ["llm"], "library_name": "transformers"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    results = manager.huggingface_search("tiny")
    assert results[0]["id"] == "org/tiny-model"
    card = manager.huggingface_model("org/tiny-model")
    assert card["library_name"] == "transformers"
    with pytest.raises(ConnectorError):
        manager.huggingface_model("bad id with space")


def test_gmail_send_and_auth_error(monkeypatch, manager):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def sendmail(self, from_addr, to, raw):
            sent["mail"] = (from_addr, to, raw)

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    manager.set_secret("gmail", "app-pass")
    result = manager.gmail_send("user@mail.ru", "Обучение завершено", "Готово!")
    assert result["ok"] is True
    assert sent["mail"][1] == ["user@mail.ru"]
    raw = sent["mail"][2]
    assert "From: me@gmail.com" in raw and "To: user@mail.ru" in raw
    assert "=?utf-8?b?" in raw  # subject/body are MIME-encoded, not plaintext

    with pytest.raises(ConnectorError):
        manager.gmail_send("bad-address", "тема", "тело")

    class FakeSMTPFail(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTPFail)
    with pytest.raises(ConnectorError, match="App Password"):
        manager.gmail_send("user@mail.ru", "t", "b")


def test_agent_tool_bridge(manager):
    handlers, schemas, mutations = manager.agent_tools()
    assert set(handlers) == {"search_github", "search_huggingface",
                             "huggingface_model_card", "send_email"}
    assert mutations == frozenset({"send_email"})
    assert len(schemas) == 4
    with pytest.raises(ConnectorError):
        handlers["send_email"]({"to": "x", "subject": "y", "body": "z"})
