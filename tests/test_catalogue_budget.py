"""Fitting a block into a token budget."""

from __future__ import annotations

import pytest

from toolform.catalogue import fit_to_budget
from toolform.sdk import render


def test_fits_as_is(real3):
    r = fit_to_budget(real3, "json_schema_openai", 100_000)
    assert r.fits and r.dropped == [] and r.tokens_after == r.tokens_before and len(r.steps) == 2
    assert r.kept == real3.names()


def test_query_drops_lowest_ranked(real_tools):
    budget = 3000
    r = fit_to_budget(real_tools, "json_schema_openai", budget, query="weather forecast in Paris")
    assert r.fits and r.tokens_after <= budget and "weather_forecast" in r.kept
    assert all(d["reason"] == "lowest BM25 score for the query" and d["tokens"] > 0 for d in r.dropped)
    assert render(r.toolset, "json_schema_openai").tokens_estimate == r.tokens_after


def test_optional_descriptions_then_tools(real3):
    full = render(real3, "json_schema_openai").tokens_estimate
    r = fit_to_budget(real3, "json_schema_openai", full - 20)
    assert r.fits and r.dropped and all("param" in d for d in r.dropped)
    for d in r.dropped:
        p = next(x for x in r.toolset.get(d["tool"]).params if x.name == d["param"])
        assert not p.required and p.description == ""
    assert all(
        p.description
        for t in r.toolset
        for p in t.params
        if p.required and next(x for x in real3.get(t.name).params if x.name == p.name).description
    )
    tight = fit_to_budget(real3, "json_schema_openai", 300)
    reasons = [d["reason"] for d in tight.dropped]
    assert "dropped from the end of the list to fit the budget" in reasons


def test_keep_and_last_tool(real3):
    r = fit_to_budget(real3, "json_schema_openai", 10, keep=["calculator"])
    assert r.kept == ["calculator"] and not r.fits
    assert "still over the budget" in r.steps[-1]
    r2 = fit_to_budget(real3, "json_schema_openai", 10)
    assert len(r2.kept) == 1 and not r2.fits
    d = r2.to_dict()
    assert d["tools"] == r2.kept and d["fits"] is False


def test_errors(real3):
    with pytest.raises(ValueError):
        fit_to_budget(real3, "json_schema_openai", 0)
    with pytest.raises(KeyError):
        fit_to_budget(real3, "json_schema_openai", 10, keep=["nope"])


@pytest.fixture
def real_tools():
    from toolform.sdk import generated_toolset

    return generated_toolset()
