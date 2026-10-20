"""Every accepted shape of each loader, detection, and loader errors."""

from __future__ import annotations

import json

import pytest

from toolform.ir import TypeKind
from toolform.sdk import LoaderError, Toolset, detect_kind, load_tools
from toolform.sdk.loaders import from_anthropic, from_ir, from_mcp, from_openai, read_source


def test_openai_list_file(fixtures_dir):
    ts = Toolset.from_openai(fixtures_dir / "openai_tools.json")
    assert ts.names() == ["get_weather", "create_event", "search_flights"]
    assert ts.source == "openai"
    w = ts.get("get_weather")
    loc, units, days = w.params
    assert loc.required and loc.type.constraints.min_length == 2
    assert units.type.kind == TypeKind.ENUM and units.type.enum_values == ("celsius", "fahrenheit")
    assert units.default == "celsius" and not units.required
    assert days.type.constraints.minimum == 1 and days.type.constraints.maximum == 14


def test_openai_ref_nested_required_and_examples(fixtures_dir):
    ev = Toolset.from_openai(str(fixtures_dir / "openai_tools.json")).get("create_event")
    by = {p.name: p for p in ev.params}
    assert by["start"].type.constraints.format == "date-time"
    assert by["start"].example == "2026-10-01T09:00:00Z"
    att = by["attendees"].type
    assert att.kind == TypeKind.ARRAY and att.constraints.min_items == 1
    fields = {f.name: f for f in att.item.fields}
    assert fields["email"].required and not fields["optional"].required and fields["optional"].default is False
    rem = by["reminder"]
    assert rem.type.kind == TypeKind.OBJECT and rem.description == "A reminder before the event."
    rf = {f.name: f for f in rem.type.fields}
    assert rf["minutes"].required and rf["minutes"].type.constraints.minimum == 0
    assert rf["method"].type.enum_values == ("email", "popup")


def test_openai_nullable_anyof_is_optional(fixtures_dir):
    fl = Toolset.from_openai(fixtures_dir / "openai_tools.json").get("search_flights")
    cabin = {p.name: p for p in fl.params}["cabin"]
    assert cabin.type.kind == TypeKind.ENUM and not cabin.required
    assert {p.name: p for p in fl.params}["origin"].type.constraints.pattern == "^[A-Z]{3}$"


def test_openai_other_shapes():
    body = {
        "name": "f",
        "description": "d",
        "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
    }
    assert from_openai([body])[0].name == "f"  # bare
    assert from_openai({"tools": [{"type": "function", "function": body}]})[0].name == "f"  # chat request body
    assert from_openai([{"type": "function", **body}])[0].params[0].name == "x"  # Responses API
    assert from_openai(json.dumps([body]))[0].params[0].type.kind == TypeKind.INTEGER  # JSON text
    assert from_openai([{"type": "function", "function": {"name": "g"}}])[0].params == ()  # no parameters


def test_anthropic(fixtures_dir):
    ts = Toolset.from_anthropic(fixtures_dir / "anthropic_tools.json")
    assert ts.names() == ["lookup_order", "refund"]
    amount = ts.get("refund").params[1]
    assert amount.type.constraints.minimum == 0  # exclusiveMinimum stored as minimum
    single = from_anthropic({"name": "x", "input_schema": {"type": "object", "properties": {}}})
    assert single[0].name == "x"


def test_mcp_list_and_annotations(fixtures_dir):
    ts = Toolset.from_mcp(fixtures_dir / "mcp_tools_list.json")
    rf = ts.get("read_file")
    assert rf.annotations["mcp"] == {
        "title": "Read a file",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }
    assert rf.returns is not None and rf.returns.kind == TypeKind.OBJECT
    assert rf.returns_description == "The file content."
    assert ts.get("list_directory").annotations == {}


def test_mcp_jsonrpc_and_bare_list(fixtures_dir):
    ts = Toolset.from_mcp(fixtures_dir / "mcp_jsonrpc.json")
    assert ts.names() == ["query_db"]
    assert ts.get("query_db").annotations["mcp"]["annotations"] == {"readOnlyHint": True}
    bare = from_mcp([{"name": "a", "inputSchema": {"type": "object", "properties": {}}}])
    assert bare[0].name == "a"
    with pytest.raises(LoaderError, match="error"):
        from_mcp({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "nope"}})


def test_ir_shapes(fixtures_dir, sample):
    ts = Toolset.from_ir(fixtures_dir / "ir_tools.json")
    assert ts.names() == ["legal_draft_v3", "convert_currency"]
    assert ts.get("legal_draft_v3").to_dict() == sample.get("legal_draft_v3").to_dict()
    assert from_ir([sample.tools[0].to_dict()])[0].name == "legal_draft_v3"
    assert from_ir({"tools": [sample.tools[0].to_dict()]})[0].name == "legal_draft_v3"
    with pytest.raises(LoaderError, match="ToolIR"):
        from_ir([{"params": []}])


def test_detect_kind(fixtures_dir, sample):
    assert detect_kind(fixtures_dir / "openai_tools.json") == "openai"
    assert detect_kind(fixtures_dir / "anthropic_tools.json") == "anthropic"
    assert detect_kind(fixtures_dir / "mcp_tools_list.json") == "mcp"
    assert detect_kind(fixtures_dir / "mcp_jsonrpc.json") == "mcp"
    assert detect_kind(fixtures_dir / "ir_tools.json") == "ir"
    assert detect_kind(sample.to_ir()["tools"]) == "ir"
    assert detect_kind(fixtures_dir / "tools.d.ts") == "typescript"
    assert detect_kind(str(fixtures_dir / "pytools.py")) == "python"
    assert detect_kind("declare function f(x: string): void;") == "typescript"
    assert detect_kind([len, print]) == "python"
    import json as json_module

    assert detect_kind(json_module) == "python"
    assert detect_kind([]) == "openai"


def test_load_tools_every_kind(fixtures_dir):
    assert load_tools(fixtures_dir / "openai_tools.json").source == "openai"
    assert load_tools(fixtures_dir / "mcp_jsonrpc.json").source == "mcp"
    assert load_tools(fixtures_dir / "tools.d.ts").source == "typescript"
    py = load_tools(fixtures_dir / "pytools.py")
    assert py.source == "python" and "paint" in py.executors
    assert load_tools(fixtures_dir / "anthropic_tools.json", kind="anthropic").names() == ["lookup_order", "refund"]
    assert Toolset.load(fixtures_dir / "ir_tools.json").source == "ir"


def test_loader_errors(fixtures_dir):
    bad = json.loads((fixtures_dir / "bad_tools.json").read_text())
    with pytest.raises(LoaderError, match="duplicate tool name 'a'"):
        from_openai(bad["duplicate"])
    with pytest.raises(LoaderError, match="no name"):
        from_openai(bad["no_name"])
    with pytest.raises(LoaderError, match="must be a JSON object"):
        from_openai(bad["parameters_not_object"])
    with pytest.raises(LoaderError, match="cannot tell"):
        detect_kind(bad["not_tools"])
    with pytest.raises(LoaderError, match="not valid JSON"):
        read_source("{not json")
    with pytest.raises(LoaderError, match="no such file"):
        load_tools(fixtures_dir / "missing.json")
    with pytest.raises(LoaderError, match="unknown kind"):
        load_tools([], kind="yaml")
    with pytest.raises(LoaderError, match="cannot tell"):
        detect_kind("just some words")


def test_read_source(fixtures_dir):
    assert isinstance(read_source(fixtures_dir / "openai_tools.json"), list)
    assert read_source("[1, 2]") == [1, 2]
    assert read_source({"a": 1}) == {"a": 1}
    assert "declare function" in read_source(fixtures_dir / "tools.d.ts")


def test_loader_error_message_carries_source_and_line():
    err = LoaderError("bad", source="x.ts", line=3)
    assert str(err) == "bad (x.ts, line 3)" and err.line == 3 and err.source == "x.ts"


def test_more_error_branches(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{\n  oops\n}")
    with pytest.raises(LoaderError) as info:
        read_source(bad)
    assert info.value.line == 2
    assert read_source(b'[{"a": 1}]') == [{"a": 1}]
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    assert read_source(txt) == "hello"
    with pytest.raises(LoaderError, match="must be a list"):
        from_openai({"tools": "x"})
    with pytest.raises(LoaderError, match="expected a JSON object or list"):
        from_openai(5)
    with pytest.raises(LoaderError, match="not a JSON object"):
        from_openai([5])
    with pytest.raises(LoaderError, match="not a JSON object"):
        from_anthropic([5])
    with pytest.raises(LoaderError, match="no name"):
        from_anthropic([{"input_schema": {}}])
    with pytest.raises(LoaderError, match="not a JSON object"):
        from_mcp([5])
    with pytest.raises(LoaderError, match="no name"):
        from_mcp([{"inputSchema": {}}])
    with pytest.raises(LoaderError, match="not JSON"):
        from_openai([{"name": "f", "parameters": "{not json"}])
    assert (
        from_openai([{"name": "f", "parameters": '{"type": "object", "properties": {"a": {"type": "string"}}}'}])[0]
        .params[0]
        .name
        == "a"
    )
    with pytest.raises(LoaderError, match="empty name"):
        from_ir([{"name": "", "params": []}])
    with pytest.raises(LoaderError, match="not a valid ToolIR"):
        from_ir([{"name": "x", "params": [{"name": "p", "type": {"kind": "weird"}}]}])
    with pytest.raises(LoaderError, match="no such file"):
        detect_kind(str(tmp_path / "missing.py"))
    with pytest.raises(LoaderError, match="no such file"):
        detect_kind(str(tmp_path / "missing.ts"))
    assert detect_kind({"name": "x", "input_schema": {}}) == "anthropic"
    assert detect_kind({"tools": []}) == "openai"
    assert detect_kind({"universe_id": "u", "tools": []}) == "ir"
    with pytest.raises(LoaderError, match="cannot tell"):
        detect_kind({"tools": [{"name": "x"}]})
    with pytest.raises(LoaderError, match="cannot tell"):
        detect_kind([{"name": "x"}])
    with pytest.raises(LoaderError, match="cannot tell"):
        detect_kind(txt)
    assert detect_kind(tmp_path / "missing.json" if False else "function f(a: string): void;") == "typescript"


def test_unknown_json_schema_type_is_a_warning():
    # Regression: "type": "strin" loaded silently as any.
    from toolform.sdk import Toolset, load_tools

    spec = [
        {
            "type": "function",
            "function": {
                "name": "f",
                "description": "d",
                "parameters": {"type": "object", "properties": {"a": {"type": "strin"}, "b": {"type": "string"}}},
            },
        }
    ]
    for ts in (Toolset.from_openai(spec), load_tools(spec)):
        assert ts.warnings == ["tool 'f': unknown JSON Schema type 'strin', read as any value"]
        assert ts.summary()["warnings"] == ts.warnings
    assert (
        Toolset.from_openai(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "g",
                        "parameters": {"type": "object", "properties": {"a": {"type": "string"}}},
                    },
                }
            ]
        ).warnings
        == []
    )


def test_a_missing_file_says_so():
    # Regression: Toolset.from_openai("nope.json") said "expected a JSON object or list ... got str".
    from toolform.sdk import LoaderError, Toolset

    for call in (Toolset.from_openai, Toolset.from_mcp, Toolset.from_anthropic, Toolset.from_ir):
        with pytest.raises(LoaderError, match="no such file"):
            call("tools/does_not_exist.json")
