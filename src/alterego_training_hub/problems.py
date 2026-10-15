"""Problem extraction from training logs (no Tk — used by UI and tests)."""
from __future__ import annotations

import re

MAX_PROBLEMS = 200

# (severity, compiled pattern, group layout)
_TRACEBACK_RE = re.compile(r"File \"([^\"]+)\", line (\d+)")
_FRAME_RE = re.compile(r"([\w./\\-]+\.[A-Za-z]{1,4}):(\d+)(?::| )")
_FAILED_RE = re.compile(r"(?:FAILED|ERROR)\s+([\w./\\-]+(?:::[\w]+)?)")
_MESSAGE_RE = re.compile(
    r"(?:AssertionError|Traceback \(most recent call last\)|"
    r"FAILED .+|ERROR: .+|[A-Za-z_]*Error\b.*|"
    r".*(?:NaN|Inf|расхождени\w+|divergence).*)")


def parse_problems(log_text: str, *, limit: int = MAX_PROBLEMS) -> list[dict]:
    """Extract file/line-addressable problems from a log tail."""
    problems: list[dict] = []
    seen: set[tuple] = set()

    def add(severity: str, message: str, path: str = "", line: int = 0):
        key = (severity, message, path, line)
        if key in seen or len(problems) >= limit:
            return
        seen.add(key)
        problems.append({"severity": severity, "message": message.strip()[:200],
                         "path": path, "line": line})

    for raw_line in log_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        match = _TRACEBACK_RE.search(line)
        if match:
            add("error", line.strip(), match.group(1), int(match.group(2)))
            continue
        match = _FAILED_RE.search(line)
        if match:
            target = match.group(1)
            path = target.split("::", 1)[0]
            add("error", line.strip(), path, 0)
            continue
        match = _FRAME_RE.search(line)
        if match and ("Error" in line or "assert" in line or "raise" in line):
            add("error", line.strip(), match.group(1), int(match.group(2)))
            continue
        if _MESSAGE_RE.match(line.strip()):
            severity = "error" if any(
                token in line for token in
                ("Error", "FAILED", "NaN", "Inf", "Traceback")) else "warn"
            add(severity, line.strip())
    return problems
