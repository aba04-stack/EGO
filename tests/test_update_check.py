"""Этап 39: проверка обновлений — версии, сравнение, офлайн-ошибки."""
from alterego_training_hub.update_check import (
    check_update,
    is_newer,
    parse_version,
    release_api_url,
)


def test_parse_and_compare_versions():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("0.35") == (0, 35, 0)
    assert parse_version("") == (0, 0, 0)
    assert is_newer("0.36.0", "0.35.0")
    assert is_newer("1.0.0", "0.99.9")
    assert not is_newer("0.35.0", "0.35.0")
    assert not is_newer("0.34.9", "0.35.0")


def test_check_update_with_fake_fetcher():
    report = check_update(
        "0.35.0",
        fetcher=lambda url: {"tag_name": "v0.36.0",
                             "html_url": "https://example/r"})
    assert report.update_available and report.latest == "0.36.0"
    assert "0.36.0" in report.render() and "https://example/r" in report.render()
    fresh = check_update("0.36.0",
                         fetcher=lambda url: {"tag_name": "v0.36.0"})
    assert not fresh.update_available
    assert "последняя версия" in fresh.render()


def test_check_update_never_raises():
    def boom(_url):
        raise ConnectionError("нет сети")

    report = check_update("0.35.0", fetcher=boom)
    assert report.error and "Не удалось проверить" in report.render()
    empty = check_update("0.35.0", fetcher=lambda url: {})
    assert empty.error


def test_release_api_url():
    assert release_api_url("aba04-stack/-").endswith(
        "repos/aba04-stack/-/releases/latest")
    assert release_api_url("/owner/repo/").endswith(
        "repos/owner/repo/releases/latest")
