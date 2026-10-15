"""Update check (этап 39): is a newer release available on GitHub?

Pure version logic + an injected fetcher (urllib by default), so it is fully
testable offline and can never break the UI: every failure becomes an
``error`` field in the report.  Compares dotted numeric versions — enough
for our ``0.x.y`` / ``1.0.0`` scheme.
"""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_REPO = "aba04-stack/-"
_API = "https://api.github.com/repos/{repo}/releases/latest"


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' / '1.2' -> (1, 2, 3) / (1, 2, 0); garbage -> (0,).

    Суффиксы предварительных выпусков ('-rc1', '+build') в числа не
    склеиваются: раньше '1.2.3-rc1' превращалась в (1, 2, 31).
    """
    raw = str(text or "").strip().lstrip("vV")
    core = raw.split("-", 1)[0].split("+", 1)[0]
    parts: list[int] = []
    for chunk in core.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _prerelease_key(text: str) -> tuple:
    """SemVer §11: релиз новее prerelease; идентификаторы через точку:
    числовые сравниваются числом и ниже буквенных, буквенные — лексически,
    меньшее число идентификаторов ниже при равном префиксе."""
    raw = str(text or "").strip().lstrip("vV")
    if "-" not in raw:
        return (1,)
    suffix = raw.split("-", 1)[1].split("+", 1)[0]
    parts: list[tuple[int, int, str]] = []
    for chunk in suffix.split("."):
        if chunk.isdigit():
            parts.append((0, int(chunk), ""))   # числовой: ниже буквенного
        else:
            parts.append((1, 0, chunk))        # буквенный: лексически целиком
    return (0, *parts)


def version_key(text: str) -> tuple:
    return (parse_version(text), _prerelease_key(text))


def is_newer(latest: str, current: str) -> bool:
    return version_key(latest) > version_key(current)


@dataclass
class UpdateReport:
    current: str
    latest: str = ""
    update_available: bool = False
    url: str = ""
    error: str = ""

    def render(self) -> str:
        if self.error == "no_releases":
            return ("Релизов не найдено. Если репозиторий приватный, "
                    "перемещён или адрес в настройках неверен, GitHub "
                    "отвечает тем же 404 — проверьте «update_repo». "
                    f"Ваша сборка: {self.current}.")
        if self.error:
            return f"Не удалось проверить обновления: {self.error}"
        if not self.latest:
            return "Релизы не найдены."
        if self.update_available:
            return (f"Доступна новая версия {self.latest} "
                    f"(у вас {self.current}).\nСкачать: {self.url}")
        return f"У вас последняя версия ({self.current})."


def release_api_url(repo: str = DEFAULT_REPO) -> str:
    slug = (repo or DEFAULT_REPO).strip().strip("/")
    return _API.format(repo=slug)


def _fetch_json(url: str, token: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "EGO-LLM-Studio"}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def check_update(current: str, *, repo: str = DEFAULT_REPO,
                 fetcher: Callable[[str], dict[str, Any]] | None = None,
                 token: str = "",
                 ) -> UpdateReport:
    """Ask GitHub for the latest release; never raises.

    404 у GitHub двусмыслен (нет релизов ИЛИ приватный/неверный репозиторий) —
    формулировка честно называет обе причины. ``token`` (GitHub PAT из
    хранилища секретов) снимает двусмысленность для приватных репозиториев.
    """
    if fetcher is not None:
        fetch = fetcher
    else:
        def fetch(url):
            return _fetch_json(url, token=token) if token else _fetch_json(url)
    try:
        data = fetch(release_api_url(repo))
    except Exception as exc:
        if "404" in str(exc):
            return UpdateReport(current=current, error="no_releases")
        return UpdateReport(current=current,
                            error=f"{type(exc).__name__}: {exc}"[:200])
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    url = str(data.get("html_url") or "").strip()
    if not tag:
        return UpdateReport(current=current, error="в ответе GitHub нет тега")
    latest = tag.lstrip("vV")
    return UpdateReport(current=current, latest=latest,
                        update_available=is_newer(latest, current), url=url)
