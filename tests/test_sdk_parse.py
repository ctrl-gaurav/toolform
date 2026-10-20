"""Parsing under the three grading rules, validation, and the protocol round trip."""

from __future__ import annotations

import pytest

from toolform.ir import ToolCall
from toolform.protocols import get_protocol, protocol_ids
from toolform.sdk import UnknownProtocolError, parse_reply, validate_arguments
from toolform.sdk.parse import AS_WRITTEN_REASON

GOLD = ToolCall(name="legal_draft_v3", arguments={"counterparty": "Acme", "value": 1000, "term_months": 12})


def test_there_are_31_protocols():
    assert len(protocol_ids()) == 31


@pytest.mark.parametrize("pid", protocol_ids())
def test_every_protocol_round_trips(sample, pid):
    text = get_protocol(pid).render_calls([GOLD])
    parsed = parse_reply(text, sample, pid)
    assert parsed.parsed_strict, text
    assert len(parsed.calls) == 1
    call = parsed.calls[0]
    assert call.resolved_name == "legal_draft_v3"
    assert call.normalized_arguments["counterparty"].lower() == "acme"
    assert float(call.normalized_arguments["value"]) == 1000 and int(call.normalized_arguments["term_months"]) == 12
    assert call.to_call().name == "legal_draft_v3"


FLAT_XML = """<function_calls>
<invoke name="legal_draft_v3">
<parameter name="counterparty">Acme</parameter>
<parameter name="value">1000</parameter>
<parameter name="term_months">12</parameter>
<parameter name="status">draft</parameter>
</invoke>
</function_calls>"""

FLAT_JSON = (
    '{"name": "legal_draft_v3", "arguments": {"counterparty": "Acme", "value": 1000, '
    '"term_months": 12, "status": "draft"}}'
)


def test_rules_under_xml_call(sample):
    main = parse_reply(FLAT_XML, sample, "xml_call", rule="main")
    assert main.calls and "renested" in main.calls[0].repairs and main.calls[0].valid
    assert main.calls[0].arguments["contract_details"] == {"status": "draft"}
    sym = parse_reply(FLAT_XML, sample, "xml_call", rule="symmetric")
    assert sym.calls and sym.calls[0].valid
    written = parse_reply(FLAT_XML, sample, "xml_call", rule="as_written")
    assert not written.calls and written.rejected[0].reason == AS_WRITTEN_REASON
    assert not written.ok


def test_rules_under_json_object(sample):
    main = parse_reply(FLAT_JSON, sample, "json_object", rule="main")
    c = main.calls[0]
    assert "status" in c.arguments and not c.valid and c.repairs == []
    assert c.validation["unknown_args"] == ["status"]
    sym = parse_reply(FLAT_JSON, sample, "json_object", rule="symmetric")
    c = sym.calls[0]
    assert c.arguments["contract_details"] == {"status": "draft"} and c.valid and "renested:status" in c.repairs
    written = parse_reply(FLAT_JSON, sample, "json_object", rule="as_written")
    assert written.calls and written.calls[0].arguments == main.calls[0].arguments


def test_conflict_is_recorded(sample):
    text = (
        '{"name": "legal_draft_v3", "arguments": {"counterparty": "A", "value": 1, "term_months": 1, '
        '"contract_details": {"status": "draft"}, "status": "signed"}}'
    )
    c = parse_reply(text, sample, "json_object", rule="symmetric").calls[0]
    assert "conflict:status" in c.repairs


def test_unknown_tool_is_rejected_and_listed(sample):
    text = '{"name": "delete_everything", "arguments": {}}'
    p = parse_reply(text, sample, "json_object")
    assert not p.calls and p.rejected[0].reason == "unknown tool" and p.hallucinated == ["delete_everything"]
    assert p.rejected[0].resolved_name is None and not p.rejected[0].valid
    assert p.rejected[0].validation["unknown_tool"]


def test_validation_errors(sample):
    bad = (
        '{"name": "legal_draft_v3", "arguments": {"counterparty": 5, "term_months": 900, '
        '"contract_details": {"status": "lost"}}}'
    )
    c = parse_reply(bad, sample, "json_object").calls[0]
    v = c.validation
    assert not c.valid and v["type_errors"] and v["missing_required"] == ["value"]
    assert v["constraint_errors"] and v["enum_errors"]
    unchecked = parse_reply(bad, sample, "json_object", validate=False).calls[0]
    assert unchecked.valid


def test_naming_convention_resolves(sample):
    p = parse_reply(
        '{"name": "LegalDraftV3", "arguments": {"counterparty": "A", "value": 1, "termMonths": 2}}',
        sample,
        "json_object",
    )
    assert p.calls[0].resolved_name == "legal_draft_v3" and p.calls[0].valid


def test_think_blocks_and_no_call(sample):
    text = "<think>maybe call it</think>" + get_protocol("json_object").render_calls([GOLD])
    p = parse_reply(text, sample, "json_object")
    assert p.reasoning_removed and p.calls
    none = parse_reply("No tool fits this request.", sample, "json_object")
    assert not none.calls and none.no_call_declared and none.ok and none.format_compliant


def test_lenient_fallback(sample):
    xml_text = get_protocol("xml_call").render_calls([GOLD])
    strict_only = parse_reply(xml_text, sample, "json_object")
    assert not strict_only.calls and strict_only.parsed_lenient and not strict_only.format_compliant
    fb = parse_reply(xml_text, sample, "json_object", lenient_fallback=True)
    assert fb.calls and fb.calls[0].repairs[0] == "lenient:xml_call"
    with pytest.raises(ValueError, match="as_written"):
        parse_reply(xml_text, sample, "json_object", rule="as_written", lenient_fallback=True)


def test_bad_rule_and_protocol(sample):
    with pytest.raises(ValueError, match="grading rule"):
        parse_reply("x", sample, "json_object", rule="loose")
    with pytest.raises(UnknownProtocolError):
        parse_reply("x", sample, "json_objekt")


def test_to_dict_and_ok(sample):
    p = parse_reply(get_protocol("json_object").render_calls([GOLD]), sample, "json_object")
    d = p.to_dict()
    assert d["ok"] and d["calls"][0]["accepted"] and d["protocol_id"] == "json_object" and d["rule"] == "main"
    import json

    json.dumps(d)


def test_validate_arguments(sample):
    assert validate_arguments(GOLD, sample).ok
    assert validate_arguments({"name": "legalDraftV3", "arguments": {"counterparty": "A"}}, sample).missing_required
    assert validate_arguments({"name": "nope", "arguments": {}}, sample).unknown_tool


# --------------------------------------------------------------------------- #
# parsing edge cases
# --------------------------------------------------------------------------- #


def _forecast():
    from toolform.sdk import Toolset

    return Toolset.from_openai(
        [
            {
                "type": "function",
                "function": {
                    "name": "get_forecast",
                    "description": "Forecast.",
                    "parameters": {
                        "type": "object",
                        "required": ["city"],
                        "properties": {
                            "city": {"type": "string"},
                            "days": {"type": "integer", "minimum": 1, "maximum": 7},
                            "sku": {"type": "string", "pattern": "^[A-Z]{3}-\\d+$"},
                        },
                    },
                },
            }
        ]
    )


def test_an_invented_tool_makes_the_reply_not_ok():
    # Regression: a valid call beside a call to a tool that does not exist was "ok".
    text = '[{"name":"get_forecast","arguments":{"city":"Denver"}},{"name":"delete_everything","arguments":{}}]'
    r = parse_reply(text, _forecast(), "json_array")
    assert r.calls and r.hallucinated == ["delete_everything"] and not r.ok
    r = parse_reply(text, _forecast(), "json_object")
    assert not r.ok


def test_as_written_rejection_makes_the_reply_not_ok(sample):
    r = parse_reply(FLAT_XML, sample, "xml_call", rule="as_written")
    assert r.rejected and not r.ok


def test_two_json_objects_under_json_object_get_a_note():
    text = '{"name":"get_forecast","arguments":{"city":"Denver"}} {"name":"get_forecast","arguments":{"city":"Oslo"}}'
    r = parse_reply(text, _forecast(), "json_object")
    assert len(r.calls) == 1 and "2 JSON objects" in r.note and "json_array" in r.note


def test_non_ascii_names_parse_under_python_call():
    # Regression: 天气_查询(城市="北京") gave no call, although Python's grammar accepts it.
    from toolform.sdk import Toolset

    ts = Toolset.from_openai(
        [
            {
                "type": "function",
                "function": {
                    "name": "天气_查询",
                    "description": "d",
                    "parameters": {"type": "object", "required": ["城市"], "properties": {"城市": {"type": "string"}}},
                },
            }
        ]
    )
    r = parse_reply('天气_查询(城市="北京")', ts, "python_call")
    assert r.ok and r.calls[0].arguments == {"城市": "北京"} and "non-ASCII" in r.note


def test_validation_checks_pattern_and_accepts_integral_floats():
    ts = _forecast()
    bad = validate_arguments({"name": "get_forecast", "arguments": {"city": "x", "sku": "abc"}}, ts)
    assert not bad.ok and any("pattern" in e for e in bad.constraint_errors)
    good = validate_arguments({"name": "get_forecast", "arguments": {"city": "x", "sku": "ABC-12", "days": 5.0}}, ts)
    assert good.ok, good.to_dict()
    over = validate_arguments({"name": "get_forecast", "arguments": {"city": "x", "days": 9.0}}, ts)
    assert not over.ok and over.constraint_errors
    frac = validate_arguments({"name": "get_forecast", "arguments": {"city": "x", "days": 2.5}}, ts)
    assert not frac.ok and frac.type_errors


def test_no_call_declarations_are_listed():
    from toolform.sdk.parse import NO_CALL_DECLARATIONS

    assert "no tool" in NO_CALL_DECLARATIONS and "i cannot" in NO_CALL_DECLARATIONS
    r = parse_reply("I cannot help with that.", _forecast(), "json_object")
    assert r.ok and r.no_call_declared and not r.calls
