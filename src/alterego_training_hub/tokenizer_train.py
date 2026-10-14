"""Minimal byte-level BPE tokenizer trainer (for the from-scratch path).

Trains merges on raw text, saves/loads a JSON vocab, encodes/decodes.
Deliberately small and dependency-free — good enough to bootstrap a toy LLM
and to *understand* tokenization; swap in HF tokenizers for production.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_TOKEN_RE = re.compile(r"\S+|\s+", re.UNICODE)


class ByteBPE:
    def __init__(self) -> None:
        self.merges: list[tuple[bytes, bytes]] = []
        self.vocab: dict[bytes, int] = {bytes([i]): i for i in range(256)}

    # ------------------------------------------------------------- training
    def train(self, text: str, *, vocab_size: int = 1000,
              min_pair_freq: int = 2) -> "ByteBPE":
        words: list[list[bytes]] = []
        for chunk in _TOKEN_RE.findall(text or ""):
            words.append([bytes([b]) for b in chunk.encode("utf-8")])
        self.merges = []
        self.vocab = {bytes([i]): i for i in range(256)}
        target = max(256, min(int(vocab_size), 50000))
        while len(self.vocab) < target:
            counts: dict[tuple[bytes, bytes], int] = {}
            for word in words:
                for a, b in zip(word, word[1:]):
                    counts[(a, b)] = counts.get((a, b), 0) + 1
            if not counts:
                break
            (a, b), freq = max(counts.items(), key=lambda kv: kv[1])
            if freq < min_pair_freq:
                break
            merged = a + b
            self.merges.append((a, b))
            self.vocab[merged] = len(self.vocab)
            new_words: list[list[bytes]] = []
            for word in words:
                out: list[bytes] = []
                i = 0
                while i < len(word):
                    if i + 1 < len(word) and word[i] == a and word[i + 1] == b:
                        out.append(merged)
                        i += 2
                    else:
                        out.append(word[i])
                        i += 1
                new_words.append(out)
            words = new_words
        return self

    # -------------------------------------------------------------- encode
    def _apply(self, chunk: bytes) -> list[bytes]:
        tokens = [bytes([b]) for b in chunk]
        for a, b in self.merges:
            merged = a + b
            out: list[bytes] = []
            i = 0
            while i < len(tokens):
                if i + 1 < len(tokens) and tokens[i] == a and tokens[i + 1] == b:
                    out.append(merged)
                    i += 2
                else:
                    out.append(tokens[i])
                    i += 1
            tokens = out
        return tokens

    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        for chunk in _TOKEN_RE.findall(text or ""):
            for token in self._apply(chunk.encode("utf-8")):
                ids.append(self.vocab[token])
        return ids

    def decode(self, ids) -> str:
        inv = {i: tok for tok, i in self.vocab.items()}
        raw = b"".join(inv.get(int(i), b"") for i in ids)
        return raw.decode("utf-8", errors="replace")

    # --------------------------------------------------------- persistence
    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "merges": [[a.decode("latin-1"), b.decode("latin-1")] for a, b in self.merges],
            "vocab_size": len(self.vocab),
        }
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "ByteBPE":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        tok = cls()
        tok.merges = []
        for a, b in raw.get("merges", []):
            pair = (a.encode("latin-1"), b.encode("latin-1"))
            tok.merges.append(pair)
            tok.vocab[pair[0] + pair[1]] = len(tok.vocab)
        return tok

    @property
    def vocab_size(self) -> int:
        return len(self.vocab)


def train_on_text(text: str, *, vocab_size: int = 1000) -> ByteBPE:
    return ByteBPE().train(text, vocab_size=vocab_size)


def compression_stats(tok: ByteBPE, text: str) -> dict:
    ids = tok.encode(text)
    chars = len(text or "")
    return {"chars": chars, "tokens": len(ids),
            "chars_per_token": round(chars / len(ids), 2) if ids else 0.0,
            "vocab_size": tok.vocab_size}
