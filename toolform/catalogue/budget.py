"""Fit a tool block into a token budget, and say exactly what was dropped.

Steps, stopping as soon as the rendered block fits (tokens estimated as
characters / 4): (1) render as is; (2) with a query, rank the tools by BM25
and drop the lowest-ranked, fewest first; (3) without a query, drop the
longest optional-parameter descriptions first (required parameters keep
theirs); (4) drop tools from the end of the list. Tools named in ``keep`` are
never dropped, and neither is the last tool: an empty block fits any budget
and serves no request, so ``fits`` is False when one tool is left over it.

Step 3 changes what the model reads. In the study, removing descriptions cost
little over all cells (-1.94 to +1.86%), except for the Python stub, whose
docstring is its parameter documentation (-12.76%).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Sequence

from ..formats import DEFAULT_OPTIONS, RenderOptions, get_format
from ..ir import ToolIR, ToolUniverse
from ..sdk.rendering import check_format
from ..sdk.tokens import estimate_tokens
from ..sdk.toolset import Toolset
from .retrieve import retrieve


@dataclass
class BudgetResult:
    """The fitted toolset and a record of every step and drop."""

    format_id: str
    budget_tokens: int
    tokens_before: int
    tokens_after: int
    kept: list[str]
    dropped: list[dict[str, Any]]
    steps: list[str]
    toolset: Toolset
    fits: bool

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict; ``toolset`` is given as its names."""
        return {
            "format_id": self.format_id,
            "budget_tokens": self.budget_tokens,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "kept": list(self.kept),
            "dropped": [dict(d) for d in self.dropped],
            "steps": list(self.steps),
            "fits": self.fits,
            "tools": self.toolset.names(),
        }


def _tokens(tools: list[ToolIR], format_id: str, options: RenderOptions) -> int:
    if not tools:
        return 0
    return estimate_tokens(get_format(format_id).render(ToolUniverse(tools=tools), options))


def _drop_param_description(tool: ToolIR, name: str) -> ToolIR:
    return replace(tool, params=tuple(replace(p, description="") if p.name == name else p for p in tool.params))


def fit_to_budget(
    toolset: Toolset,
    format_id: str,
    budget_tokens: int,
    *,
    query: str | None = None,
    keep: Sequence[str] = (),
    options: RenderOptions | None = None,
) -> BudgetResult:
    """Shrink ``toolset`` until its ``format_id`` block fits ``budget_tokens``."""
    check_format(format_id)
    if budget_tokens < 1:
        raise ValueError("budget_tokens must be at least 1")
    opts = options or DEFAULT_OPTIONS
    keep_names = []
    for k in keep:
        t = toolset.get(k)
        if t is None:
            raise KeyError(f"no tool named {k!r}")
        keep_names.append(t.name)
    tools = list(toolset.tools)
    before = _tokens(tools, format_id, opts)
    steps = [
        f"rendered {len(tools)} tools in {format_id}: about {before:,} tokens against a budget of {budget_tokens:,}"
    ]
    dropped: list[dict[str, Any]] = []
    now = before

    def fits() -> bool:
        return now <= budget_tokens

    if not fits() and query:
        ranked = [n for n, _ in retrieve(toolset, query, k=len(toolset), method="bm25").ranked]
        order = [n for n in reversed(ranked) if n not in keep_names]
        steps.append("ranked the tools against the query by BM25 and dropped the lowest-ranked first")
        for name in order:
            if fits() or len(tools) <= 1:
                break
            remaining = [t for t in tools if t.name != name]
            after = _tokens(remaining, format_id, opts)
            dropped.append({"tool": name, "reason": "lowest BM25 score for the query", "tokens": now - after})
            tools, now = remaining, after
    if not fits() and not query:
        descs = sorted(
            ((len(p.description), t.name, p.name) for t in tools for p in t.params if not p.required and p.description),
            reverse=True,
        )
        if descs:
            steps.append("removed the longest optional-parameter descriptions first; required parameters keep theirs")
        for _, tname, pname in descs:
            if fits():
                break
            new_tools = [_drop_param_description(t, pname) if t.name == tname else t for t in tools]
            after = _tokens(new_tools, format_id, opts)
            dropped.append(
                {
                    "tool": tname,
                    "param": pname,
                    "reason": "optional parameter description removed",
                    "tokens": now - after,
                }
            )
            tools, now = new_tools, after
    if not fits():
        steps.append("dropped tools from the end of the list")
        for t in list(reversed(tools)):
            if fits() or len(tools) <= 1:
                break
            if t.name in keep_names:
                continue
            remaining = [x for x in tools if x.name != t.name]
            after = _tokens(remaining, format_id, opts)
            dropped.append(
                {"tool": t.name, "reason": "dropped from the end of the list to fit the budget", "tokens": now - after}
            )
            tools, now = remaining, after
    ok = fits()
    steps.append(
        f"about {now:,} tokens with {len(tools)} tools: "
        + ("fits" if ok else "still over the budget; nothing left to drop")
    )
    result_ts = Toolset(
        universe=ToolUniverse(tools=tools, universe_id=toolset.universe.universe_id, meta=dict(toolset.universe.meta)),
        source=toolset.source,
        executors={n: f for n, f in toolset.executors.items() if n in {t.name for t in tools}},
    )
    return BudgetResult(
        format_id=format_id,
        budget_tokens=budget_tokens,
        tokens_before=before,
        tokens_after=now,
        kept=[t.name for t in tools],
        dropped=dropped,
        steps=steps,
        toolset=result_ts,
        fits=ok,
    )


__all__ = ["BudgetResult", "fit_to_budget"]
