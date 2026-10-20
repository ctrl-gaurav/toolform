"""The SDK's JSON Schema converter, which keeps constraints."""

from __future__ import annotations

from toolform.ir import TypeKind
from toolform.sdk.jsonschema import params_from_json_schema, tool_from_function_schema, type_from_json_schema


def test_scalars_and_constraints():
    t = type_from_json_schema({"type": "string", "minLength": 1, "maxLength": 5, "pattern": "^a", "format": "email"})
    c = t.constraints
    assert (t.kind, c.min_length, c.max_length, c.pattern, c.format) == (TypeKind.STRING, 1, 5, "^a", "email")
    n = type_from_json_schema({"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 10})
    assert (n.constraints.minimum, n.constraints.maximum) == (0, 10)
    assert type_from_json_schema({"type": "integer", "minimum": True}).constraints.minimum is None
    a = type_from_json_schema({"type": "array", "items": {"type": "boolean"}, "minItems": 1, "maxItems": 3})
    assert a.item.kind == TypeKind.BOOLEAN and (a.constraints.min_items, a.constraints.max_items) == (1, 3)
    assert type_from_json_schema({"type": "null"}).kind == TypeKind.NULL
    assert type_from_json_schema({}).kind == TypeKind.ANY
    assert type_from_json_schema(None).kind == TypeKind.ANY
    assert type_from_json_schema({"type": "mystery"}).kind == TypeKind.ANY
    assert type_from_json_schema({"items": {"type": "string"}}).kind == TypeKind.ARRAY


def test_enums_const_and_bases():
    assert type_from_json_schema({"enum": [1, 2]}).base == TypeKind.INTEGER
    assert type_from_json_schema({"enum": [1.5, 2]}).base == TypeKind.NUMBER
    assert type_from_json_schema({"enum": [True, False]}).base == TypeKind.BOOLEAN
    assert type_from_json_schema({"enum": ["a", 1]}).base == TypeKind.STRING
    assert type_from_json_schema({"type": "number", "enum": [1, 2]}).base == TypeKind.NUMBER
    c = type_from_json_schema({"const": "fixed"})
    assert c.kind == TypeKind.ENUM and c.enum_values == ("fixed",)
    p = params_from_json_schema({"type": "object", "properties": {"e": {"enum": ["a", None]}}, "required": ["e"]})
    assert p[0].type.enum_values == ("a",) and not p[0].required


def test_unions_and_nullability():
    u = type_from_json_schema({"anyOf": [{"type": "string"}, {"type": "integer"}]})
    assert u.kind == TypeKind.UNION and [x.kind for x in u.union_of] == [TypeKind.STRING, TypeKind.INTEGER]
    o = type_from_json_schema({"oneOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]})
    assert o.kind == TypeKind.UNION and len(o.union_of) == 2
    m = type_from_json_schema({"type": ["string", "integer"]})
    assert m.kind == TypeKind.UNION
    assert type_from_json_schema({"type": ["string"]}).kind == TypeKind.STRING
    ps = params_from_json_schema(
        {
            "type": "object",
            "required": ["a", "b", "c"],
            "properties": {
                "a": {"type": ["string", "null"]},
                "b": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "c": {"oneOf": [{"type": "string"}, {"const": None}]},
            },
        }
    )
    assert [(p.type.kind, p.required) for p in ps] == [
        (TypeKind.STRING, False),
        (TypeKind.INTEGER, False),
        (TypeKind.STRING, False),
    ]


def test_refs_all_of_and_recursion():
    defs = {
        "A": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        "Loop": {"type": "object", "properties": {"next": {"$ref": "#/definitions/Loop"}}},
    }
    a = type_from_json_schema({"$ref": "#/$defs/A"}, defs)
    assert a.kind == TypeKind.OBJECT and a.fields[0].required
    assert type_from_json_schema({"$ref": "A"}, defs).kind == TypeKind.OBJECT  # bare name
    assert type_from_json_schema({"$ref": "#/$defs/Missing"}, defs).kind == TypeKind.ANY
    loop = type_from_json_schema({"$ref": "#/definitions/Loop"}, defs)
    depth = 0
    t = loop
    while t.kind == TypeKind.OBJECT and t.fields:
        t = t.fields[0].type
        depth += 1
    assert depth <= 13  # stops, no recursion error
    merged = type_from_json_schema(
        {
            "allOf": [
                {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
                {"properties": {"b": {"type": "integer"}}, "required": ["b"]},
            ]
        }
    )
    assert [f.name for f in merged.fields] == ["a", "b"] and all(f.required for f in merged.fields)
    one = type_from_json_schema({"allOf": [{"$ref": "#/$defs/A"}], "description": "d"}, defs)
    assert one.kind == TypeKind.OBJECT
    ps = params_from_json_schema({"allOf": [{"type": "object", "properties": {"q": {"type": "string"}}}]})
    assert ps[0].name == "q"
    tuple_items = type_from_json_schema({"type": "array", "items": [{"type": "string"}, {"type": "integer"}]})
    assert tuple_items.item.kind == TypeKind.UNION
    assert type_from_json_schema({"type": "array", "items": [{"type": "string"}]}).item.kind == TypeKind.STRING


def test_params_details_and_sibling_keys():
    ps = params_from_json_schema(
        {
            "type": "object",
            "$defs": {"R": {"type": "integer", "description": "From def."}},
            "properties": {
                "r": {"$ref": "#/$defs/R", "default": 3},
                "s": {"type": "string", "examples": ["ex"]},
                "t": "not a schema",
            },
        }
    )
    r, s, t = ps
    assert r.type.kind == TypeKind.INTEGER and r.description == "From def." and r.default == 3
    assert s.example == "ex" and t.type.kind == TypeKind.ANY
    assert params_from_json_schema(None) == () and params_from_json_schema({"type": "object"}) == ()


def test_tool_from_function_schema_with_returns():
    t = tool_from_function_schema(
        "f",
        "Does f.",
        {"type": "object", "properties": {}},
        returns={"type": "object", "description": "the result"},
        annotations={"mcp": {"title": "F"}},
    )
    assert t.returns.kind == TypeKind.OBJECT and t.returns_description == "the result"
    assert t.domain == "user" and t.origin == "user" and t.annotations == {"mcp": {"title": "F"}}
    assert tool_from_function_schema("g", "", None).params == ()
