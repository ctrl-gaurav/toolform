"""Retrieval before presenting."""

from __future__ import annotations

import importlib.util

import pytest

from toolform.catalogue import retrieve
from toolform.ir import ToolIR
from toolform.sdk import Toolset


def _tiny() -> Toolset:
    return Toolset.from_tools(
        [
            ToolIR(name="send_email", description="Send an email message to a recipient."),
            ToolIR(name="get_weather", description="Get the weather forecast for a city."),
            ToolIR(name="book_flight", description="Book a flight between two airports."),
            ToolIR(name="weather_alerts", description="List weather alerts for a region."),
            ToolIR(name="noop", description="Does nothing."),
        ],
        executors={"get_weather": lambda city: city},
    )


def test_bm25_order_ties_and_k():
    r = retrieve(_tiny(), "weather forecast for Paris", k=2)
    assert [n for n, _ in r.ranked][:2] == ["get_weather", "weather_alerts"]
    assert r.toolset.names() == ["get_weather", "weather_alerts"]
    zeros = [n for n, s in r.ranked if s == 0]
    assert zeros == ["send_email", "book_flight", "noop"]  # ties keep catalogue order
    assert r.method == "bm25" and r.query == "weather forecast for Paris"
    assert set(r.toolset.executors) == {"get_weather"}
    d = r.to_dict()
    assert d["selected"] == ["get_weather", "weather_alerts"] and d["k"] == 2


def test_keep_takes_slots():
    r = retrieve(_tiny(), "weather", k=2, keep=["noop"])
    top = r.ranked[0][0]
    assert top in ("get_weather", "weather_alerts")
    assert set(r.toolset.names()) == {"noop", top} and len(r.toolset) == 2
    r2 = retrieve(_tiny(), "weather", k=1, keep=["noop", "book_flight"])
    assert set(r2.toolset.names()) == {"noop", "book_flight"}
    with pytest.raises(KeyError):
        retrieve(_tiny(), "x", keep=["nope"])


def test_errors():
    with pytest.raises(ValueError, match="method"):
        retrieve(_tiny(), "x", method="tfidf")
    with pytest.raises(ValueError, match="k must"):
        retrieve(_tiny(), "x", k=0)


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is not None,
    reason="sentence-transformers is installed; the embed path would load a model",
)
def test_embed_needs_sentence_transformers():
    with pytest.raises(ImportError, match="sentence-transformers"):
        retrieve(_tiny(), "weather", method="embed")


def test_real_catalogue(real3):
    r = retrieve(real3, "calculate 2 plus 2", k=1)
    assert r.toolset.names() == ["calculator"]
