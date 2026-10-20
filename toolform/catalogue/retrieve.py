"""Retrieve before presenting: show the model the tools most like the request.

The study's evidence: on a 128-tool panel, showing the top 8 by BM25 reached
31.19% against 12.70% for the whole panel (55 checkpoints, tab_count). The
gold tool is not forced in, so a retrieval miss makes the request
unanswerable; retrieval runs per request, because it needs the request text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..generator.retrieval import bm25_scores, tool_text
from ..sdk.toolset import Toolset

METHODS = ("bm25", "embed")


@dataclass
class Retrieval:
    """The ranked catalogue and the top ``k`` as a Toolset."""

    query: str
    method: str
    ranked: list[tuple[str, float]]
    toolset: Toolset

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict; ``toolset`` is given as its names."""
        return {
            "query": self.query,
            "method": self.method,
            "ranked": [[n, round(s, 6)] for n, s in self.ranked],
            "selected": self.toolset.names(),
            "k": len(self.toolset),
        }


def _embed_scores(query: str, docs: list[str]) -> list[float]:
    try:
        import sentence_transformers  # noqa: F401  (checked before the model loads)
    except ImportError as exc:
        raise ImportError(
            "the embed retriever needs the sentence-transformers package: pip install sentence-transformers"
        ) from exc
    from ..generator.retrieval import embed_scores

    return embed_scores(query, docs)


def retrieve(toolset: Toolset, query: str, *, k: int = 8, method: str = "bm25", keep: Sequence[str] = ()) -> Retrieval:
    """Rank the tools against ``query`` and keep the top ``k``.

    ``bm25`` is the study's in-house BM25 over each tool's name, description
    and parameter text. ``embed`` uses a sentence embedding and needs
    ``sentence-transformers``. Tools named in ``keep`` are always included and
    take slots from the top ``k``. Ties keep catalogue order.
    """
    if method not in METHODS:
        raise ValueError(f"unknown retrieval method {method!r}; use one of {', '.join(METHODS)}")
    if k < 1:
        raise ValueError("k must be at least 1")
    tools = toolset.tools
    docs = [tool_text(t) for t in tools]
    scores = bm25_scores(query, docs) if method == "bm25" else _embed_scores(query, docs)
    order = sorted(range(len(tools)), key=lambda i: (-scores[i], i))
    ranked = [(tools[i].name, float(scores[i])) for i in order]
    kept: list[str] = []
    for n in keep:
        t = toolset.get(n)
        if t is None:
            raise KeyError(f"no tool named {n!r}")
        if t.name not in kept:
            kept.append(t.name)
    selected = list(kept)
    for name, _ in ranked:
        if len(selected) >= max(k, len(kept)):
            break
        if name not in selected:
            selected.append(name)
    rank_of = {name: i for i, (name, _) in enumerate(ranked)}
    selected.sort(key=lambda n: rank_of[n])
    by_name = {t.name: t for t in tools}
    sub = Toolset.from_tools(
        [by_name[n] for n in selected],
        name=f"{toolset.universe.universe_id}:top{k}",
        source=toolset.source,
        executors={n: f for n, f in toolset.executors.items() if n in selected},
    )
    return Retrieval(query=query, method=method, ranked=ranked, toolset=sub)


__all__ = ["METHODS", "Retrieval", "retrieve"]
