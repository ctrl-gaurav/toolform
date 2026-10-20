"""Rendering reproduces the study's prompt exactly."""

from __future__ import annotations

import pytest

from toolform.formats import DEFAULT_OPTIONS, format_ids, get_format
from toolform.generator.tasks import TaskInstance, Turn
from toolform.prompts import PromptSpec
from toolform.prompts import build_messages as study_build_messages
from toolform.protocols import get_protocol
from toolform.sdk import (
    TWO_STAGE_FORMATS,
    Toolset,
    UnknownFormatError,
    UnknownProtocolError,
    build_messages,
    compare_formats,
    render,
    render_options,
)
from toolform.sdk.rendering import check_format, default_protocol, study_format_ids


@pytest.mark.parametrize(
    "fid,pid",
    [
        ("xml_schema", None),
        ("json_schema_openai", "xml_call"),
        ("natural_language", None),
        ("typescript", "tool_call_tags"),
    ],
)
def test_render_equals_study_prompt(sample, fid, pid):
    rp = render(sample, fid, pid, request="Draft a contract with Acme for 1000 over 12 months.")
    inst = TaskInstance(
        instance_id="sdk",
        regime="single",
        turns=[Turn(user="Draft a contract with Acme for 1000 over 12 months.")],
        universe=sample.universe,
    )
    expected = study_build_messages(
        inst, PromptSpec(format_id=fid, protocol_id=pid or get_format(fid).meta.default_protocol)
    )
    assert rp.messages == expected
    assert rp.system_prompt == expected[0]["content"]
    assert rp.tool_block == get_format(fid).render(sample.universe, DEFAULT_OPTIONS)
    assert rp.tool_block in rp.system_prompt and rp.instructions in rp.system_prompt
    assert rp.chars == len(rp.tool_block) and rp.tokens_estimate == max(1, round(len(rp.tool_block) / 4))
    assert rp.protocol_id == (pid or get_format(fid).meta.default_protocol)


def test_default_protocol_and_no_request(sample):
    rp = render(sample, "xml_schema")
    assert rp.protocol_id == "xml_call" and rp.messages is None
    assert rp.instructions == get_protocol("xml_call").instructions(sample.universe)
    d = rp.to_dict()
    assert d["format"]["id"] == "xml_schema" and isinstance(d["format"]["tags"], list)
    assert default_protocol("python_stub") == "python_call"


def test_options_persona_trust_line(sample):
    bare = render(sample, "json_schema_openai", options=render_options(descriptions=False))
    assert "Other party." not in bare.tool_block
    assert render_options(minify=True).minify and render_options(case_convention="camel").case_convention == "camel"
    rp = render(sample, "xml_schema", persona="bare", null_clause=False, trust_line=True, request="x")
    from toolform.prompts import NULL_CLAUSE, PERSONAS
    from toolform.prompts.templates import TRUST_LINE

    assert PERSONAS["agent"] not in rp.system_prompt and NULL_CLAUSE not in rp.system_prompt
    assert TRUST_LINE in rp.system_prompt
    with pytest.raises(ValueError, match="persona"):
        render(sample, "xml_schema", persona="pirate")


def test_build_messages(sample):
    msgs = build_messages(sample, "hello", format_id="yaml_schema")
    assert msgs[-1] == {"role": "user", "content": "hello"} and msgs[0]["role"] == "system"


def test_two_stage_and_unknown_ids(sample):
    for fid in TWO_STAGE_FORMATS:
        with pytest.raises(ValueError, match="two-stage format; use toolform.catalogue.TwoStage"):
            render(sample, fid)
    with pytest.raises(UnknownFormatError) as info:
        render(sample, "xml_schemaa")
    assert "xml_schema" in str(info.value) and isinstance(info.value, KeyError)
    with pytest.raises(UnknownProtocolError) as info2:
        render(sample, "xml_schema", "xml_cal")
    assert "xml_call" in str(info2.value)
    check_format("names_then_schema", allow_two_stage=True)


def test_compare_formats_covers_129(sample):
    rows = compare_formats(sample)
    assert len(rows) == 129 == len(study_format_ids())
    assert not any(r["error"] for r in rows)
    tokens = [r["tokens_estimate"] for r in rows]
    assert tokens == sorted(tokens)
    assert {r["format_id"] for r in rows} == set(format_ids()) - set(TWO_STAGE_FORMATS)
    xml = next(r for r in rows if r["format_id"] == "xml_schema")
    assert xml["study_accuracy"] is not None and xml["default_protocol"] == "xml_call"
    assert any(r["novel"] for r in rows)


def test_compare_formats_keeps_one_basis(sample):
    """Regression: core rows took tab_main and the rest the export, about ten points apart, in one column."""
    from toolform.advisor.evidence import load_evidence
    from toolform.sdk import CORE_FORMATS

    ev = load_evidence()
    rows = {r["format_id"]: r for r in compare_formats(sample)}
    measured = [r for r in rows.values() if r["study_accuracy"] is not None]
    assert measured and all(r["study_source"] == "export:format_leaderboard" for r in measured)
    for fid in CORE_FORMATS:
        assert rows[fid]["study_accuracy"] == ev.format_meta(fid)["measured"]["call_exact"]
        assert rows[fid]["paper_accuracy"] == ev.core_accuracy(fid, "main")
    assert rows["xml_schema"]["paper_accuracy"] == 67.52 and rows["json_schema_openai"]["paper_accuracy"] == 53.71
    assert all(r["paper_accuracy"] is None for f, r in rows.items() if f not in CORE_FORMATS)


def test_render_writes_non_identifier_names_in_snake_case_for_code_formats():
    # Regression: python_stub printed "def get-user(...)" and the parser then found no call.
    from toolform.sdk import parse_reply

    ts = Toolset.from_openai(
        [
            {
                "type": "function",
                "function": {
                    "name": n,
                    "description": "d.",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
                },
            }
            for n in ("get-user", "web search")
        ]
    )
    for fid in ("python_stub", "typescript", "rust_signature"):
        r = render(ts, fid)
        assert "get-user(" not in r.tool_block and "web search(" not in r.tool_block
        assert "get_user" in r.tool_block and any("snake case" in w for w in r.warnings)
    assert not render(ts, "json_schema_openai").warnings
    got = parse_reply('get_user(q="x")', ts, "python_call")
    assert got.ok and got.calls[0].resolved_name == "get-user"


def test_render_names_required_fields_a_format_hides():
    # Regression: xml_schema printed <items type="object"/> and hid the required sku and qty.
    ts = Toolset.from_openai(
        [
            {
                "type": "function",
                "function": {
                    "name": "create_order",
                    "description": "Create an order.",
                    "parameters": {
                        "type": "object",
                        "required": ["items"],
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["sku", "qty"],
                                    "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}},
                                },
                            }
                        },
                    },
                },
            }
        ]
    )
    r = render(ts, "xml_schema")
    assert {(h["path"], h["required"]) for h in r.hidden_fields} == {("items[].sku", True), ("items[].qty", True)}
    assert any("does not show 2 required fields" in w for w in r.warnings)
    assert render(ts, "json_schema_openai").hidden_fields == []


def test_compare_formats_subset_and_errors(sample, monkeypatch):
    rows = compare_formats(sample, ["xml_schema", "json_minimal"])
    assert [r["format_id"] for r in rows] == ["json_minimal", "xml_schema"]
    with pytest.raises(UnknownFormatError):
        compare_formats(sample, ["nope"])
    renderer = get_format("yaml_schema")

    def boom(*a, **k):
        raise RuntimeError("renderer broke")

    monkeypatch.setattr(renderer, "render", boom)
    rows = compare_formats(sample, ["yaml_schema", "xml_schema"])
    bad = rows[-1]
    assert bad["format_id"] == "yaml_schema" and "renderer broke" in bad["error"] and bad["tokens_estimate"] is None


def test_the_module_is_not_shadowed_by_the_function():
    # Regression: toolform.sdk.render was both a module and a function, so patching the module did nothing.
    import importlib

    import toolform.sdk as sdk

    mod = importlib.import_module("toolform.sdk.rendering")
    assert callable(sdk.render) and mod.render is sdk.render and hasattr(mod, "estimate_tokens")
