"""Local retrieval: file sources, paragraph chunks, BM25 ranking."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from keel_core.errors import KeelError
from keel_core.ports import Document
from keel_local.guardrails import looks_like_injection

CHUNK_TARGET_CHARS = 800
MAX_FILE_BYTES = 2_000_000
_TOKEN = re.compile(r"\w+")
_SUFFIXES = {".md", ".txt"}
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def chunk_paragraphs(text: str, *, target: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Split on blank lines, then merge small neighbours until a chunk reaches ``target``."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > target:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def resolve_file_source(uri: str, base_dir: Path) -> Path:
    """Turn ``file://<path>`` into a path inside ``base_dir``; anything else is an error."""
    if not uri.startswith("file://"):
        scheme = uri.split("://", 1)[0] if "://" in uri else uri
        raise KeelError(f"rag source '{uri}': scheme '{scheme}' is not available in local mode")
    base = base_dir.resolve()
    path = (base / uri.removeprefix("file://")).resolve()
    if not path.is_relative_to(base):
        raise KeelError(f"rag source '{uri}' is outside the spec directory")
    if not path.exists():
        raise KeelError(f"rag source not found: {uri}")
    return path


@dataclass(frozen=True, slots=True)
class _Chunk:
    source: str
    ref: str
    text: str
    terms: Counter[str]
    length: int
    suspicious: bool


class LocalRetriever:
    """Loads every source once at start-up and ranks chunks with BM25.

    ``sources`` maps a spec source name to a file or directory (``.md`` and ``.txt`` only).
    Only chunks from the requested sources are scored, so statistics never leak across them.
    """

    def __init__(self, sources: Mapping[str, Path]) -> None:
        self._chunks: dict[str, list[_Chunk]] = {
            name: self._load(name, p) for name, p in sources.items()
        }

    @staticmethod
    def _load(name: str, root: Path) -> list[_Chunk]:
        if root.is_dir():
            found = sorted(f for f in root.rglob("*") if f.is_file() and f.suffix in _SUFFIXES)
            files = [(f, f.relative_to(root).as_posix()) for f in found]
        else:
            files = [(root, root.name)]
        chunks: list[_Chunk] = []
        for file, rel in files:
            if file.stat().st_size > MAX_FILE_BYTES:
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            for n, piece in enumerate(chunk_paragraphs(text), start=1):
                tokens = tokenize(piece)
                chunks.append(
                    _Chunk(
                        source=name,
                        ref=f"{name}/{rel}#{n}",
                        text=piece,
                        terms=Counter(tokens),
                        length=len(tokens),
                        suspicious=looks_like_injection(piece),
                    )
                )
        return chunks

    async def retrieve(self, query: str, *, sources: frozenset[str], top_k: int) -> list[Document]:
        pool = [c for name in sorted(sources) for c in self._chunks.get(name, [])]
        q_terms = set(tokenize(query))
        if not pool or not q_terms:
            return []
        n_docs = len(pool)
        avg_len = sum(c.length for c in pool) / n_docs or 1.0
        scored: list[tuple[float, int, _Chunk]] = []
        for idx, chunk in enumerate(pool):
            score = 0.0
            for term in q_terms:
                tf = chunk.terms.get(term, 0)
                if not tf:
                    continue
                df = sum(1 for c in pool if term in c.terms)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * chunk.length / avg_len))
            if score > 0:
                scored.append((score, idx, chunk))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [
            Document(
                source=c.source,
                text=c.text,
                ref=c.ref,
                score=round(score, 6),
                labels=frozenset({"trust:untrusted", "scan:suspicious-instruction"})
                if c.suspicious
                else frozenset({"trust:internal"}),
            )
            for score, _, c in scored[:top_k]
        ]
