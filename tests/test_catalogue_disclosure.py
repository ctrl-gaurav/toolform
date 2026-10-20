"""Names-first two-stage disclosure."""

from __future__ import annotations

import pytest

from toolform.catalogue import SELECTION_ASK, TwoStage
from toolform.sdk import StubClient, UnknownFormatError


def test_selection_ask_names_one_tool():
    assert "exact name of the one tool" in SELECTION_ASK


def test_selection_messages(real3):
    two = TwoStage(real3)
    msgs = two.selection_messages("what is 2+2")
    assert msgs[-1]["content"] == "what is 2+2" + SELECTION_ASK
    system = msgs[0]["content"]
    assert all(n in system for n in real3.names())
    assert real3.get("calculator").description.split(". ")[0].rstrip(".") in system
    names_only = TwoStage(real3, include_descriptions=False).selection_messages("x")[0]["content"]
    assert real3.get("calculator").description.split(". ")[0] not in names_only
    assert two.selection_format == "names_desc_then_schema"


def test_parse_selection(real3):
    two = TwoStage(real3)
    assert two.parse_selection("I would use the github tool.") == "github"
    assert two.parse_selection("`weather`") == "weather"
    assert two.parse_selection("CALCULATOR") == "calculator"
    assert two.parse_selection("none of these") is None and two.parse_selection("") is None


def test_longest_match_wins(weather):
    from toolform.ir import ToolIR
    from toolform.sdk import Toolset

    ts = Toolset.from_tools([ToolIR(name="get"), ToolIR(name="get_weather")])
    assert TwoStage(ts).parse_selection("get_weather please") == "get_weather"


def test_run_two_calls_and_failure(real3):
    client = StubClient(["weather", '{"name": "weather", "arguments": {"location": "Oslo"}}'])
    res = TwoStage(real3).run(client, "weather in Oslo")
    assert res.selected == "weather" and not res.selection_failed and len(client.calls) == 2
    assert res.parsed.calls and res.parsed.calls[0].resolved_name == "weather"
    assert "calculator" not in client.calls[1][0]["content"]
    assert res.prompt_tokens > 0 and res.completion_tokens > 0 and res.to_dict()["selected"] == "weather"
    fail_client = StubClient(["I am not sure."])
    fail = TwoStage(real3).run(fail_client, "hmm")
    assert fail.selection_failed and fail.parsed is None and len(fail_client.calls) == 1


def test_call_messages_and_errors(real3):
    two = TwoStage(real3, format_id="xml_schema", protocol_id="xml_call")
    msgs = two.call_messages("q", "github")
    assert "<name>github</name>" in msgs[0]["content"] and "calculator" not in msgs[0]["content"]
    with pytest.raises(KeyError):
        two.call_messages("q", "nope")
    with pytest.raises(UnknownFormatError):
        TwoStage(real3, format_id="nope")
    with pytest.raises(ValueError):
        TwoStage(real3, rule="loose")
