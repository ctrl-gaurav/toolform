"""Retrieve before presenting.

The practitioner's card says "retrieve or route before presenting" and no
experiment did it. Given a request and a panel of tools, rank the panel by
a retriever over each tool's text (its name with the underscores taken out,
its description, its parameter names and descriptions) and show the top k.
Two retrievers: BM25 (in-house, no dependency) and a sentence embedding
(all-MiniLM-L6-v2 through sentence-transformers, on the CPU, cached per
process). The gold tool is not forced in: when the retriever misses it the
instance is unanswerable, and that miss is the cost the experiment measures
(recall of the gold tool is recorded on every instance).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Sequence

from ..ir import ToolIR

RETRIEVERS = ("none", "bm25", "embed")
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_TOKEN = re.compile(r"[a-z0-9]+")


def tool_text(tool: ToolIR) -> str:
    """The text a retriever indexes for one tool."""
    bits = [tool.name.replace("_", " "), tool.description]
    for p in tool.params:
        bits.append(p.name.replace("_", " "))
        if p.description:
            bits.append(p.description)
    return " ".join(b for b in bits if b)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def bm25_scores(query: str, docs: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25 of the query against each document."""
    toks = [_tokens(d) for d in docs]
    n = len(toks)
    avg = sum(len(t) for t in toks) / max(1, n)
    df: Counter[str] = Counter()
    for t in toks:
        df.update(set(t))
    q = _tokens(query)
    out: list[float] = []
    for t in toks:
        tf = Counter(t)
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / max(1e-9, avg)))
        out.append(s)
    return out


@lru_cache(maxsize=1)
def _embedder():
    import os

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from sentence_transformers import SentenceTransformer  # type: ignore

    return SentenceTransformer(EMBED_MODEL, device="cpu")


_DOC_CACHE: dict[tuple[str, ...], Any] = {}


def embed_scores(query: str, docs: Sequence[str]) -> list[float]:
    """Cosine similarity of the query embedding to each document embedding.
    Document embeddings are cached per distinct document list (one panel)."""
    key = tuple(docs)
    m = _embedder()
    if key not in _DOC_CACHE:
        _DOC_CACHE[key] = m.encode(list(docs), normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    d = _DOC_CACHE[key]
    q = m.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
    return [float(x) for x in (d @ q)]


def rank_tools(query: str, tools: Sequence[ToolIR], retriever: str) -> list[ToolIR]:
    """The panel ordered by the retriever's score, best first; ties keep panel order."""
    if retriever not in RETRIEVERS or retriever == "none":
        raise ValueError(f"retriever must be bm25 or embed, not {retriever!r}")
    docs = [tool_text(t) for t in tools]
    scores = bm25_scores(query, docs) if retriever == "bm25" else embed_scores(query, docs)
    order = sorted(range(len(tools)), key=lambda i: (-scores[i], i))
    return [tools[i] for i in order]
