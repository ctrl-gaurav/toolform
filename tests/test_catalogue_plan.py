"""The catalogue planner agrees with the advisor on the same inputs."""

from __future__ import annotations

import pytest

from toolform.advisor import recommend
from toolform.advisor.recommend import catalogue_advice
from toolform.catalogue import plan_catalogue
from toolform.ir import ParamIR, ToolIR, TypeIR
from toolform.sdk import Toolset, generated_toolset, render


def _n_tools(n: int) -> Toolset:
    return Toolset.from_tools(
        [
            ToolIR(name=f"tool_{i}", description=f"Tool number {i}.", params=(ParamIR("x", TypeIR.string()),))
            for i in range(n)
        ]
    )


@pytest.mark.parametrize("n", [1, 8, 31, 32, 63, 64, 128, 256])
def test_same_strategy_as_the_advisor(n):
    ts = _n_tools(n)
    plan = plan_catalogue(ts, format_id="xml_schema")
    tokens = render(ts, "xml_schema").tokens_estimate
    assert plan.strategy == catalogue_advice(n, tokens, None).strategy
    assert plan.strategy == recommend(tools=ts, candidates=("xml_schema",)).catalogue.strategy
    assert plan.schema_tokens == tokens and plan.n_tools == n and plan.evidence


def test_context_window_overflow():
    ts = _n_tools(8)
    tokens = render(ts, "xml_schema").tokens_estimate
    assert plan_catalogue(ts, context_tokens=tokens).strategy == "two_stage"
    assert plan_catalogue(ts, context_tokens=tokens * 4).strategy == "one_shot"


def test_budget_two_stage_or_retrieve():
    real = generated_toolset()
    small = real.subset(real.names()[:20])
    over = plan_catalogue(small, format_id="json_schema_openai", budget_tokens=500)
    assert over.strategy == "two_stage" and over.selection_messages is None
    with_q = plan_catalogue(small, format_id="json_schema_openai", budget_tokens=3000, query="search the web")
    assert with_q.strategy == "retrieve" and with_q.retrieval is not None and "over the budget" in with_q.reason
    too_small = plan_catalogue(small, format_id="json_schema_openai", budget_tokens=50, query="search the web")
    assert too_small.strategy == "two_stage" and too_small.selection_messages


def test_plans_carry_retrieval_or_selection():
    real = generated_toolset()
    r = plan_catalogue(real.subset(real.names()[:40]), query="weather in Oslo")
    assert r.strategy == "retrieve" and r.retrieval.toolset and len(r.retrieval.toolset) == 8
    t = plan_catalogue(real, query="weather in Oslo")
    assert t.strategy == "two_stage" and t.selection_messages[-1]["content"].startswith("weather in Oslo")
    d = t.to_dict()
    assert d["strategy"] == "two_stage" and d["retrieval"] is None
    # Regression: an empty catalogue was planned, citing evidence "at 4 tools" for 0 tools.
    with pytest.raises(ValueError, match="empty"):
        plan_catalogue(Toolset.from_tools([]))
