"""Plan how to show a catalogue: all at once, retrieved per request, or names first.

The planner uses the advisor's own thresholds (two-stage from 64 tools or when
the block would take more than half the context window; retrieval from 32
tools), from the same evidence, so the two never disagree. A block over the
token budget makes the plan two-stage, unless a query lets retrieval fit it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..advisor.evidence import EvidenceRow
from ..advisor.recommend import catalogue_advice
from ..sdk.rendering import check_format, render
from ..sdk.toolset import Toolset
from .disclosure import TwoStage
from .retrieve import Retrieval, retrieve


@dataclass
class CataloguePlan:
    """The chosen strategy and what it rests on."""

    strategy: str
    n_tools: int
    format_id: str
    schema_tokens: int
    context_tokens: int | None
    reason: str
    evidence: list[EvidenceRow]
    retrieval: Retrieval | None = None
    selection_messages: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "strategy": self.strategy,
            "n_tools": self.n_tools,
            "format_id": self.format_id,
            "schema_tokens": self.schema_tokens,
            "context_tokens": self.context_tokens,
            "reason": self.reason,
            "evidence": [e.to_dict() for e in self.evidence],
            "retrieval": self.retrieval.to_dict() if self.retrieval else None,
            "selection_messages": self.selection_messages,
        }


def plan_catalogue(
    toolset: Toolset,
    *,
    format_id: str = "xml_schema",
    context_tokens: int | None = None,
    budget_tokens: int | None = None,
    query: str | None = None,
    k: int = 8,
) -> CataloguePlan:
    """Choose one-shot, retrieval or two-stage disclosure for ``toolset``.

    With ``query``, a ``retrieve`` plan carries the retrieval and a
    ``two_stage`` plan carries the selection prompt for that request.
    """
    check_format(format_id)
    n = len(toolset)
    if n == 0:
        raise ValueError("the toolset is empty; give at least one tool")
    tokens = render(toolset, format_id).tokens_estimate
    advice = catalogue_advice(n, tokens, context_tokens, budget_tokens=budget_tokens)
    strategy, reason, rows = advice.strategy, advice.reason, list(advice.evidence)
    retrieval = None
    if budget_tokens is not None and tokens > budget_tokens and query:
        r = retrieve(toolset, query, k=k)
        r_tokens = render(r.toolset, format_id).tokens_estimate
        if r_tokens <= budget_tokens:
            strategy = "retrieve"
            retrieval = r
            reason = (
                f"The whole block (about {tokens:,} tokens) is over the budget of {budget_tokens:,}; the top "
                f"{len(r.toolset)} tools by BM25 for this request take about {r_tokens:,}, so retrieve them. "
                f"The gold tool is not forced in, so a retrieval miss makes a request unanswerable."
            )
    if strategy == "retrieve" and retrieval is None and query:
        retrieval = retrieve(toolset, query, k=k)
    selection = TwoStage(toolset).selection_messages(query) if strategy == "two_stage" and query else None
    return CataloguePlan(
        strategy=strategy,
        n_tools=n,
        format_id=format_id,
        schema_tokens=tokens,
        context_tokens=context_tokens,
        reason=reason,
        evidence=rows,
        retrieval=retrieval,
        selection_messages=selection,
    )


__all__ = ["CataloguePlan", "plan_catalogue"]
