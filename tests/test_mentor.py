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
