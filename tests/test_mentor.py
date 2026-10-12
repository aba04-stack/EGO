import json

import pytest

from alterego_training_hub.mentor import ApiMentor, MentorError, chat_endpoint


def test_chat_endpoint_appends_route():
    assert chat_endpoint("https://api.example.test/v1/") == "https://api.example.test/v1/chat/completions"


@pytest.mark.parametrize("url", [
    "http://api.example.test/v1",
    "https://user:password@example.test/v1",
    "https://api.example.test/v1?secret=x",
    "invalid",
])
def test_rejects_unsafe_mentor_urls(url):
    with pytest.raises(MentorError):
        chat_endpoint(url)


def test_api_mentor_parses_compatible_response(monkeypatch):
    mentor = ApiMentor("https://api.example.test/v1", "mentor-test", "test-key")

    class FakeResponse:
        headers = {"x-request-id": "request-test"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=-1):
            return json.dumps({
                "model": "mentor-test",
                "choices": [{"message": {"content": "  Good result. "}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://api.example.test/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer test-key"
        assert json.loads(request.data)["model"] == "mentor-test"
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    reply = mentor.ask("Check this", max_tokens=50)
    assert reply.text == "Good result."
    assert reply.usage["completion_tokens"] == 3
    assert reply.request_id == "request-test"


def test_empty_model_or_key_is_rejected():
    with pytest.raises(MentorError):
        ApiMentor("https://api.example.test/v1", "", "key")
    with pytest.raises(MentorError):
        ApiMentor("https://api.example.test/v1", "model", "")


@pytest.mark.parametrize("max_tokens,temperature", [
    (0, 0.2),
    (8001, 0.2),
    ("many", 0.2),
    (50, -0.1),
    (50, 2.5),
    (50, "hot"),
])
def test_ask_rejects_invalid_generation_parameters(max_tokens, temperature):
    mentor = ApiMentor("https://api.example.test/v1", "mentor-test", "test-key")
    with pytest.raises(MentorError):
        mentor.ask("Check this", max_tokens=max_tokens, temperature=temperature)


def test_respond_parses_native_tool_calls(monkeypatch):
    mentor = ApiMentor("https://api.example.test/v1", "mentor-test", "test-key")

    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=-1):
            return json.dumps({
                "model": "mentor-test",
                "choices": [{"message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call-9",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"},
                    }],
                }}],
                "usage": {"total_tokens": 7},
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        assert body["tools"][0]["function"]["name"] == "read_file"
        assert body["tool_choice"] == "auto"
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    reply = mentor.respond(
        [{"role": "user", "content": "прочитай"}],
        tools=[{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
    )
    assert reply.text == ""
    assert reply.tool_calls[0].name == "read_file"
    assert reply.tool_calls[0].arguments == {"path": "a.py"}


def test_models_endpoint_and_list_models(monkeypatch):
    from alterego_training_hub.mentor import models_endpoint

    assert models_endpoint("https://api.example.test/v1/") == "https://api.example.test/v1/models"
    assert models_endpoint("https://api.example.test/v1/chat/completions") == (
        "https://api.example.test/v1/models"
    )

    mentor = ApiMentor("https://api.example.test/v1", "mentor-test", "test-key")

    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit=-1):
            return json.dumps({"data": [{"id": "gpt-x"}, {"id": "mentor-test"},
                                        {"id": "gpt-x"}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://api.example.test/v1/models"
        assert request.get_header("Authorization") == "Bearer test-key"
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert mentor.list_models() == ["gpt-x", "mentor-test"]


def test_respond_rejects_corrupt_history():
    mentor = ApiMentor("https://api.example.test/v1", "mentor-test", "test-key")
    with pytest.raises(MentorError):
        mentor.respond([])
    with pytest.raises(MentorError):
        mentor.respond([{"content": "no role"}])
    with pytest.raises(MentorError):
        mentor.respond(["not a dict"])
