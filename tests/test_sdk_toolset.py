"""Toolset operations and the tier estimate."""

from __future__ import annotations

import pytest

from toolform.ir import ParamIR, ToolIR, TypeIR, TypeKind
from toolform.sdk import LoaderError, Toolset


def _t(name: str, *params: ParamIR) -> ToolIR:
    return ToolIR(name=name, params=params)


S = TypeIR(kind=TypeKind.STRING)


@pytest.mark.parametrize(
    "tool,tier",
    [
        (_t("flat", ParamIR("a", S), ParamIR("b", TypeIR.integer())), 1),
        (_t("enum", ParamIR("a", TypeIR.enum_of(["x", "y"]))), 2),
        (_t("optional", ParamIR("a", S, required=False)), 2),
        (_t("constraint", ParamIR("a", TypeIR.integer(minimum=1))), 2),
        (_t("nested", ParamIR("a", TypeIR.object_of([ParamIR("b", S)]))), 3),
        (_t("array", ParamIR("a", TypeIR.array_of(S))), 3),
        (_t("two_deep", ParamIR("a", TypeIR.object_of([ParamIR("b", TypeIR.object_of([ParamIR("c", S)]))]))), 4),
        (_t("one_union", ParamIR("a", TypeIR.union_of_types([S, TypeIR.integer()]))), 4),
        (
            _t(
                "three_deep",
                ParamIR(
                    "a",
                    TypeIR.object_of(
                        [ParamIR("b", TypeIR.object_of([ParamIR("c", TypeIR.object_of([ParamIR("d", S)]))]))]
                    ),
                ),
            ),
            5,
        ),
        (
            _t(
                "two_unions",
                ParamIR("a", TypeIR.union_of_types([S, TypeIR.integer()])),
                ParamIR("b", TypeIR.union_of_types([S, TypeIR.boolean()])),
            ),
            5,
        ),
    ],
)
def test_tier_estimate(tool, tier):
    assert Toolset.from_tools([tool]).tier_estimate() == tier


def test_tier_is_the_hardest_tool_and_empty_is_one():
    ts = Toolset.from_tools([_t("a", ParamIR("x", S)), _t("b", ParamIR("x", TypeIR.object_of([ParamIR("y", S)])))])
    assert ts.tier_estimate() == 3
    assert Toolset.from_tools([]).tier_estimate() == 1


def test_access_and_naming_conventions(weather):
    assert len(weather) == 3 and weather.names() == ["get_weather", "get_forecast", "set_alert"]
    assert weather.get("getWeather").name == "get_weather"
    assert "GetForecast" in weather and "nope" not in weather and 3 not in weather
    assert [t.name for t in weather] == weather.names() == [t.name for t in weather.tools]
    assert "Toolset(" in repr(weather)


def test_subset_replace_and_descriptions(weather):
    sub = weather.subset(["set_alert", "get_weather"])
    assert sub.names() == ["get_weather", "set_alert"]
    assert set(sub.executors) == {"get_weather", "set_alert"}
    with pytest.raises(KeyError):
        weather.subset(["nope"])
    new = ToolIR(name="get_weather", description="Changed.")
    rep = weather.replace_tool(new)
    assert rep.get("get_weather").description == "Changed." and weather.get("get_weather").description != "Changed."
    with pytest.raises(KeyError):
        weather.replace_tool(ToolIR(name="other"))
    bare = weather.without_descriptions(["get_forecast"])
    assert bare.get("get_forecast").description == "" and bare.get("get_weather").description
    assert all(t.description == "" for t in weather.without_descriptions())


def test_complexity_summary_fingerprint(weather, sample):
    c = weather.complexity()
    assert set(c["per_tool"]) == set(weather.names()) and c["max_depth"] == 1 and c["tier_estimate"] == 3
    assert c["n_params_max"] == 2
    s = sample.summary()
    assert s["n_tools"] == 1 and s["names"] == ["legal_draft_v3"] and s["tier_estimate"] == 3
    assert s["source"] == "sample" and s["fingerprint"] == sample.fingerprint()
    assert sample.fingerprint() == Toolset.from_ir(sample.to_ir()).fingerprint()


def test_from_tools_rejects_duplicates_and_non_tools():
    with pytest.raises(LoaderError, match="duplicate"):
        Toolset.from_tools([ToolIR(name="a"), ToolIR(name="a")])
    with pytest.raises(LoaderError, match="not a ToolIR"):
        Toolset.from_tools(["a"])  # type: ignore[list-item]
