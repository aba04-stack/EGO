"""Pure parsing helpers for the Git source-control panel (no subprocess)."""
from __future__ import annotations

STATUS_LABELS: dict[str, str] = {
    "M": "изменён",
    "A": "добавлен",
    "D": "удалён",
    "R": "переименован",
    "C": "скопирован",
    "U": "конфликт",
    "T": "тип изменён",
    "?": "не под индексом",
    "!": "игнорируется",
}


def _label(index: str, worktree: str) -> str:
    if index == "?" and worktree == "?":
        return STATUS_LABELS["?"]
    if index == "!" and worktree == "!":
        return STATUS_LABELS["!"]
    code = worktree if worktree not in (" ", "?") else index
    return STATUS_LABELS.get(code, "изменён")


def parse_porcelain(text: str) -> list[dict]:
    """Parse `git status --porcelain` output into structured rows.

    Each row: ``{"path", "original", "index", "worktree", "staged",
    "unstaged", "label"}``. Renames ("R  old -> new") keep both names.
    """
    rows: list[dict] = []
    for line in text.splitlines():
        if len(line) < 3:
            continue
        index, worktree, rest = line[0], line[1], line[2:]
        # Porcelain pads the status with one space before the path.
        rest = rest[1:] if rest.startswith(" ") else rest
        original = ""
        if " -> " in rest:
            original, rest = rest.split(" -> ", 1)
        path = rest.strip()
        if not path:
            continue
        untracked = index == "?" and worktree == "?"
        ignored = index == "!" and worktree == "!"
        rows.append({
            "path": path,
            "original": original,
            "index": index,
            "worktree": worktree,
            "staged": not (untracked or ignored or index in " ?"),
            "unstaged": not (ignored or worktree in " ?"),
            "label": _label(index, worktree),
        })
    return rows


def parse_numstat(text: str) -> list[dict]:
    """Parse `git diff --numstat` rows: ``{path, added, removed, binary}``."""
    rows: list[dict] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        binary = added == "-" or removed == "-"
        rows.append({
            "path": path,
            "added": 0 if binary else int(added),
            "removed": 0 if binary else int(removed),
            "binary": binary,
        })
    return rows


def stat_totals(rows: list[dict]) -> tuple[int, int]:
    """Total (added, removed) lines across numstat rows."""
    return (
        sum(row["added"] for row in rows),
        sum(row["removed"] for row in rows),
    )


_DIFF_META_PREFIXES = (
    "diff ", "index ", "--- ", "+++ ", "new file", "deleted file",
    "rename ", "similarity ", "copy ", "old mode", "new mode",
)


def classify_diff_lines(text: str) -> list[tuple[str, str]]:
    """Split a unified diff into ``[(kind, line)]`` for colouring.

    ``kind`` is one of: ``add``, ``del``, ``hunk``, ``meta``, ``ctx``.
    """
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if line.startswith(_DIFF_META_PREFIXES):
            kind = "meta"
        elif line.startswith("@@"):
            kind = "hunk"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "del"
        else:
            kind = "ctx"
        out.append((kind, line))
    return out
