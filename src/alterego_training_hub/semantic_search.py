"""Semantic code search (stage 40).

Workspace files are split into chunks, each chunk gets an embedding
vector, and a query is ranked by cosine similarity.  Two embedders:

* :class:`HashEmbedder` — fully local and offline: token hashing into a
  fixed-size normalized vector.  No model download, no keys; quality is
  modest but it works everywhere, including inside the packaged .exe.
* :class:`ApiEmbedder` — OpenAI-compatible ``/embeddings`` endpoint via
  an injectable transport (tests pass a fake; the app passes urllib).

The index is cached as JSON (per-chunk file mtime+size fingerprint), so
rebuilding after small edits re-embeds only changed files.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules",
                ".mypy_cache", ".pytest_cache", ".ruff_cache"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
                 ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c",
                 ".h", ".cpp", ".hpp", ".sh", ".ps1", ".html", ".css"}
MAX_FILE_BYTES = 512_000
CHUNK_LINES = 40
CHUNK_OVERLAP = 10

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9_]+")


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        tokens.append(raw)
        # split snake_case / camelCase so "train_loop" matches "trainLoop"
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw).replace("_", " ")
        tokens.extend(p.lower() for p in parts.split() if p.lower() != raw)
    return tokens


class HashEmbedder:
    """Deterministic offline embedder: hashed token counts, L2-normalized."""


    def __init__(self, dim: int = 384):
        self.dim = dim
        self.id = f"hash-v1-{dim}"

    def __call__(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:2], "little") % self.dim
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vec[idx] += sign
            # second hash spreads collisions a bit
            idx2 = int.from_bytes(digest[3:5], "little") % self.dim
            vec[idx2] += 0.5 * sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class ApiEmbedder:
    """OpenAI-compatible embeddings endpoint with injectable transport."""

    def __init__(self, base_url: str, model: str, api_key: str = "",
                 transport: Callable[[str, dict, dict], dict] | None = None):
        self.id = f"api:{model}"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.transport = transport or _urllib_transport

    @property
    def url(self) -> str:
        return f"{self.base_url}/embeddings"

    def __call__(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        out: list[list[float]] = []
        for start in range(0, len(texts), 64):
            batch = texts[start:start + 64]
            data = self.transport(
                self.url, headers, {"model": self.model, "input": batch})
            rows = sorted(data.get("data", []),
                          key=lambda r: r.get("index", 0))
            if len(rows) != len(batch):
                raise ValueError("embeddings: провайдер вернул "
                                 f"{len(rows)} векторов на {len(batch)} текстов")
            out.extend([list(map(float, r["embedding"])) for r in rows])
        return out


def _urllib_transport(url: str, headers: dict, payload: dict) -> dict:
    import urllib.request
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


@dataclass
class Chunk:
    path: str          # relative to workspace root
    line: int          # 1-based first line
    text: str
    vector: list[float] = field(default_factory=list)


@dataclass
class Hit:
    path: str
    line: int
    score: float
    snippet: str


def chunk_text(rel: str, text: str) -> list[Chunk]:
    lines = text.splitlines()
    chunks: list[Chunk] = []
    step = max(1, CHUNK_LINES - CHUNK_OVERLAP)
    for start in range(0, len(lines), step):
        block = lines[start:start + CHUNK_LINES]
        if not any(line.strip() for line in block):
            continue
        chunks.append(Chunk(path=rel, line=start + 1,
                            text="\n".join(block)))
        if start + CHUNK_LINES >= len(lines):
            break
    return chunks


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


class SemanticIndex:
    """In-memory index + JSON cache keyed by file fingerprints."""

    def __init__(self, root: Path, embedder: Callable | None = None):
        self.root = Path(root)
        self.embedder = embedder or HashEmbedder()
        self.chunks: list[Chunk] = []
        self._fingerprints: dict[str, str] = {}

    # ------------------------------------------------------------- build
    def iter_files(self) -> list[Path]:
        files: list[Path] = []
        for item in sorted(self.root.rglob("*")):
            if not item.is_file() or item.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = item.relative_to(self.root)
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            try:
                if item.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(item)
        return files

    def build(self, cached: dict[str, Any] | None = None) -> dict[str, int]:
        """(Re)build; ``cached`` is a previous :meth:`to_cache` payload."""
        old: dict[str, list[Chunk]] = {}
        old_fp: dict[str, str] = {}
        if cached and cached.get("embedder") not in (None, self.embedder_id):
            cached = None  # vectors from another embedder are incomparable
        if cached:
            old_fp = dict(cached.get("fingerprints", {}))
            for raw in cached.get("chunks", []):
                chunk = Chunk(path=raw["path"], line=raw["line"],
                              text=raw["text"], vector=raw["vector"])
                old.setdefault(chunk.path, []).append(chunk)
        self.chunks = []
        self._fingerprints = {}
        fresh_texts: list[str] = []
        fresh_chunks: list[Chunk] = []
        stats = {"files": 0, "reused": 0, "embedded": 0}
        for path in self.iter_files():
            rel = str(path.relative_to(self.root))
            stats["files"] += 1
            fingerprint = _fingerprint(path)
            self._fingerprints[rel] = fingerprint
            if old_fp.get(rel) == fingerprint and rel in old:
                self.chunks.extend(old[rel])
                stats["reused"] += 1
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for chunk in chunk_text(rel, text):
                fresh_chunks.append(chunk)
                fresh_texts.append(chunk.text)
        if fresh_texts:
            vectors = self.embedder(fresh_texts)
            for chunk, vector in zip(fresh_chunks, vectors, strict=True):
                chunk.vector = vector
                self.chunks.append(chunk)
                stats["embedded"] += 1
        return stats

    # ------------------------------------------------------------- cache
    @property
    def embedder_id(self) -> str:
        return str(getattr(self.embedder, "id", "custom"))

    def to_cache(self) -> dict[str, Any]:
        return {
            "version": 1,
            "embedder": self.embedder_id,
            "fingerprints": self._fingerprints,
            "chunks": [{"path": c.path, "line": c.line, "text": c.text,
                        "vector": c.vector} for c in self.chunks],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_cache(), ensure_ascii=False),
                        encoding="utf-8")

    @staticmethod
    def load_cache(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    # ------------------------------------------------------------- query
    def search(self, query: str, top_k: int = 20) -> list[Hit]:
        if not query.strip() or not self.chunks:
            return []
        (qvec,) = self.embedder([query])
        hits = [Hit(path=c.path, line=c.line,
                    score=cosine(qvec, c.vector),
                    snippet=next((ln.strip() for ln in c.text.splitlines()
                                  if ln.strip()), "")[:200])
                for c in self.chunks]
        hits.sort(key=lambda h: h.score, reverse=True)
        return [h for h in hits[:top_k] if h.score > 0.0]
