"""Export and load back: every field JSON Schema carries survives."""

from __future__ import annotations

from typing import Any

import pytest

from toolform.ir import ParamIR, ToolIR, TypeIR
from toolform.sdk import Toolset, generated_toolset, sample_toolset, to_anthropic, to_ir, to_mcp, to_openai
from toolform.sdk.loaders import from_anthropic, from_ir, from_mcp, from_openai


def _carried_type(t: dict[str, Any]) -> dict[str, Any]:
    out = dict(t)
    if out.get("kind") == "enum" and "base" not in out:
        out["base"] = "string"  # an ENUM with no base renders and reloads as string
    if "item" in out:
        out["item"] = _carried_type(out["item"])
    if "fields" in out:
        out["fields"] = [_carried_param(f) for f in out["fields"]]
    if "union_of" in out:
        out["union_of"] = [_carried_type(u) for u in out["union_of"]]
    return out


def _carried_param(p: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in p.items() if k != "example"}
    out["type"] = _carried_type(out["type"])
    return out


def carried(tool: ToolIR) -> dict[str, Any]:
    """What JSON Schema carries: name, description, and parameters with every type detail."""
    d = tool.to_dict()
    return {"name": d["name"], "description": d["description"], "params": [_carried_param(p) for p in d["params"]]}


def _deep_tool() -> ToolIR:
    return ToolIR(
        name="deep_tool",
        description="A tool nested three levels with a union.",
        params=(
            ParamIR(
                name="a",
                required=True,
                description="Level one.",
                type=TypeIR.object_of(
                    [
                        ParamIR(
                            name="b",
                            required=True,
                            description="Level two.",
                            type=TypeIR.object_of(
                                [
                                    ParamIR(
                                        name="c",
                                        required=False,
                                        description="Level three.",
                                        type=TypeIR.object_of(
                                            [
                                                ParamIR(
                                                    name="d",
                                                    type=TypeIR.string(pattern="^x", max_length=9),
                                                    required=True,
                                                ),
                                            ]
                                        ),
                                    ),
                                ]
                            ),
                        ),
                    ]
                ),
            ),
            ParamIR(name="u", required=False, type=TypeIR.union_of_types([TypeIR.string(), TypeIR.integer()])),
            ParamIR(
                name="tags",
                required=False,
                type=TypeIR.array_of(
                    TypeIR.enum_of(
                        [1, 2, 3],
                    ),
                    min_items=1,
                    max_items=3,
                ),
                default=[1],
            ),
            ParamIR(name="flag", required=False, type=TypeIR.boolean(), default=False),
            ParamIR(name="score", required=False, type=TypeIR.number(minimum=-1.5, maximum=2)),
        ),
    )


def _toolsets() -> list[Toolset]:
    real = generated_toolset()
    return [sample_toolset(), real, Toolset.from_tools([_deep_tool()])]


@pytest.mark.parametrize("ts", _toolsets(), ids=["sample", "real66", "deep"])
def test_openai_round_trip(ts):
    back = from_openai(to_openai(ts.tools))
    assert [carried(t) for t in back] == [carried(t) for t in ts.tools]


@pytest.mark.parametrize("ts", _toolsets(), ids=["sample", "real66", "deep"])
def test_anthropic_round_trip(ts):
    back = from_anthropic(to_anthropic(ts.tools))
    assert [carried(t) for t in back] == [carried(t) for t in ts.tools]


@pytest.mark.parametrize("ts", _toolsets(), ids=["sample", "real66", "deep"])
def test_mcp_round_trip(ts):
    back = from_mcp(to_mcp(ts.tools))
    assert [carried(t) for t in back] == [carried(t) for t in ts.tools]


@pytest.mark.parametrize("ts", _toolsets(), ids=["sample", "real66", "deep"])
def test_ir_round_trip_is_exact(ts):
    back = from_ir(to_ir(ts.tools))
    assert [t.to_dict() for t in back] == [t.to_dict() for t in ts.tools]


def test_mcp_annotations_restored(fixtures_dir):
    ts = Toolset.from_mcp(fixtures_dir / "mcp_tools_list.json")
    out = to_mcp(ts.tools)["tools"][0]
    assert out["title"] == "Read a file"
    assert out["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
    assert out["outputSchema"]["description"] == "The file content."
    again = from_mcp(to_mcp(ts.tools))
    assert again[0].annotations == ts.tools[0].annotations


def test_export_shapes(sample):
    o = to_openai(sample.tools)[0]
    assert o["type"] == "function" and "returns" not in o["function"]
    assert "description" not in to_openai(sample.tools, descriptions=False)[0]["function"]
    a = to_anthropic(sample.tools)[0]
    assert set(a) == {"name", "description", "input_schema"}
    assert to_ir(sample.tools)["tools"][0]["name"] == "legal_draft_v3"
    assert sample.to_openai() == to_openai(sample.tools)
    assert sample.to_anthropic() == to_anthropic(sample.tools)
    assert sample.to_mcp() == to_mcp(sample.tools)
    assert sample.to_ir() == to_ir(sample.tools)
