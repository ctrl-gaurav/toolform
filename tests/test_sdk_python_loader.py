"""Python functions to the IR: type mapping, docstrings, the decorator, executors, errors."""

from __future__ import annotations

import collections.abc as cabc
import dataclasses
import enum
import typing
from typing import Any, Literal, Optional, TypedDict

import pytest

from toolform.ir import TypeKind
from toolform.sdk import LoaderError, Toolset, tool
from toolform.sdk.pyintrospect import from_python, parse_docstring, tool_from_callable


def test_module_file_takes_only_decorated(fixtures_dir):
    ts = Toolset.from_python(fixtures_dir / "pytools.py")
    assert ts.names() == ["paint", "move_point", "pack"]
    assert set(ts.executors) == {"paint", "move_point", "pack"}
    assert ts.executors["pack"](box=None, items=["a", "b"]) == 2


def test_only_decorated_false_takes_every_public_function(fixtures_dir):
    ts = Toolset.from_python(str(fixtures_dir / "pytools.py"), only_decorated=False)
    assert "helper" in ts.names() and "_private" not in ts.names()


def test_type_mapping(fixtures_dir):
    ts = Toolset.from_python(fixtures_dir / "pytools.py")
    paint = {p.name: p for p in ts.get("paint").params}
    assert paint["shape"].type.kind == TypeKind.STRING and paint["shape"].required
    assert paint["color"].type.kind == TypeKind.ENUM and paint["color"].type.enum_values == ("red", "green")
    assert paint["opacity"].type.kind == TypeKind.NUMBER and paint["opacity"].default == 1.0
    assert not paint["opacity"].required
    move = {p.name: p for p in ts.get("move_point").params}
    assert move["point"].type.kind == TypeKind.OBJECT
    assert [f.name for f in move["point"].type.fields] == ["x", "y"]
    assert move["mode"].type.enum_values == ("abs", "rel") and move["mode"].default == "rel"
    pack = {p.name: p for p in ts.get("pack").params}
    assert pack["box"].type.kind == TypeKind.OBJECT
    box = {f.name: f for f in pack["box"].type.fields}
    assert box["width"].required and not box["height"].required and box["height"].default == 1
    assert pack["items"].type.kind == TypeKind.ARRAY and pack["items"].type.item.kind == TypeKind.STRING
    assert pack["note"].type.kind == TypeKind.STRING and not pack["note"].required
    assert pack["weights"].type.kind == TypeKind.ARRAY and pack["weights"].type.item.kind == TypeKind.NUMBER
    assert pack["meta"].type.kind == TypeKind.OBJECT and not pack["meta"].required
    assert pack["code"].type.kind == TypeKind.UNION


def test_docstrings(fixtures_dir):
    ts = Toolset.from_python(fixtures_dir / "pytools.py")
    paint = ts.get("paint")
    assert paint.description == "Paint a shape."
    assert paint.params[0].description == "Name of the shape."
    assert paint.returns_description == "the painted shape"
    assert ts.get("move_point").description == "Move a point by an offset."
    items = {p.name: p for p in ts.get("pack").params}["items"]
    assert items.description == "Item names, one per entry."


def test_parse_docstring_plain():
    desc, args, ret = parse_docstring("""Do a thing.

    More detail that is not the first paragraph.

    Args:
        x (int): The x.
        y: The y,
            continued.

    Returns:
        The result.
    """)
    assert desc == "Do a thing." and args == {"x": "The x.", "y": "The y, continued."} and ret == "The result."
    assert parse_docstring(None) == ("", {}, "")


class Mode(enum.Enum):
    A = 1
    B = 2


class Opts(TypedDict, total=False):
    depth: int
    label: str


@dataclasses.dataclass
class Pair:
    left: str
    right: str = "r"


def all_types(
    s: str,
    i: int,
    f: float,
    b: bool,
    lst: list[int],
    tup: tuple[str, int],
    seq: typing.Sequence[str],
    d: dict,
    lit: Literal[1, 2],
    e: Mode,
    opt: Optional[int],
    un: int | str,
    anyv: Any,
    td: Opts,
    dc: Pair,
    ann: typing.Annotated[str, "Annotated text."],
    nn: None = None,
) -> None:
    pass


def test_every_supported_hint():
    with pytest.warns(UserWarning):
        t = tool_from_callable(all_types)
    p = {x.name: x for x in t.params}
    kinds = {k: v.type.kind for k, v in p.items()}
    assert kinds["s"] == TypeKind.STRING and kinds["i"] == TypeKind.INTEGER and kinds["f"] == TypeKind.NUMBER
    assert kinds["b"] == TypeKind.BOOLEAN and kinds["lst"] == TypeKind.ARRAY and kinds["seq"] == TypeKind.ARRAY
    assert p["tup"].type.constraints.min_items == 2 and p["tup"].type.item.kind == TypeKind.UNION
    assert kinds["d"] == TypeKind.OBJECT and kinds["td"] == TypeKind.OBJECT and kinds["dc"] == TypeKind.OBJECT
    assert p["lit"].type.enum_values == (1, 2) and p["lit"].type.base == TypeKind.INTEGER
    assert p["e"].type.enum_values == (1, 2)
    assert kinds["opt"] == TypeKind.INTEGER and not p["opt"].required
    assert kinds["un"] == TypeKind.UNION and kinds["anyv"] == TypeKind.ANY
    assert not any(f.required for f in p["td"].type.fields)
    assert p["ann"].description == "Annotated text."
    assert kinds["nn"] == TypeKind.NULL
    assert t.returns is None


def test_missing_annotation_warns():
    def f(x, y: int):  # noqa: ANN001
        return x

    with pytest.warns(UserWarning, match="no annotation"):
        t = tool_from_callable(f)
    assert t.params[0].type.kind == TypeKind.ANY


def test_decorator_bare_and_with_arguments():
    @tool
    def a(x: int) -> int:
        """A."""
        return x

    @tool(name="bee", description="Custom.")
    def b(x: int) -> int:
        return x

    assert a.__toolform_tool__ == {"name": "a", "description": None}
    assert a(3) == 3
    ts = Toolset.from_python([a, b])
    assert ts.names() == ["a", "bee"] and ts.get("bee").description == "Custom."
    assert ts.executors["bee"](x=2) == 2


def test_sequence_only_decorated():
    @tool
    def a(x: int) -> int:
        return x

    def c(x: int) -> int:
        return x

    tools, ex = from_python([a, c], only_decorated=True)
    assert [t.name for t in tools] == ["a"]
    tools, ex = from_python(c)
    assert [t.name for t in tools] == ["c"]


def test_unsupported_signatures_raise():
    def star(*args: int) -> None:
        pass

    def kw(**kwargs: int) -> None:
        pass

    def pos(x: int, /) -> None:
        pass

    for fn in (star, kw, pos):
        with pytest.raises(LoaderError):
            tool_from_callable(fn)
    with pytest.raises(LoaderError, match="lambda"):
        tool_from_callable(lambda x: x)


def test_module_name_and_errors(fixtures_dir):
    tools, _ = from_python("toolform.sdk.cost", only_decorated=False)
    assert "cost_of" in [t.name for t in tools]
    with pytest.raises(LoaderError, match="cannot import"):
        from_python("no_such_module_anywhere_xyz")
    with pytest.raises(LoaderError, match="no such file"):
        from_python(str(fixtures_dir / "missing.py"))
    with pytest.raises(LoaderError):
        from_python({"a": 1})
    with pytest.raises(LoaderError, match="not callable"):
        from_python([1, 2])


def test_file_that_fails_to_run(tmp_path):
    bad = tmp_path / "boom.py"
    bad.write_text("raise RuntimeError('boom')\n")
    with pytest.raises(LoaderError, match="RuntimeError: boom"):
        from_python(bad)
    empty = tmp_path / "empty.py"
    empty.write_text("X = 1\n")
    with pytest.raises(LoaderError, match="no public functions"):
        from_python(empty)


class FakeModel:
    @classmethod
    def model_json_schema(cls):
        return {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


class BrokenModel:
    @classmethod
    def model_json_schema(cls):
        raise RuntimeError("no")


class Unknown:
    pass


def test_local_names_in_postponed_annotations():
    class Local:
        pass

    def f(a: int, b: Local) -> None:
        pass

    with pytest.warns(UserWarning):
        t = tool_from_callable(f)
    assert [p.type.kind for p in t.params] == [TypeKind.INTEGER, TypeKind.ANY]


def test_more_hints_and_models():
    def f(
        a: set[int],
        b: frozenset,
        c: tuple,
        d: list,
        e: cabc.Mapping[str, int],
        m: FakeModel,
        bm: BrokenModel,
        lit: Optional[Literal["x"]] = None,
        two: Literal["a"] | Literal["b"] = "a",
        u: Unknown = None,
    ) -> str:
        return ""

    with pytest.warns(UserWarning, match="no IR type"):
        t = tool_from_callable(f)
    p = {x.name: x for x in t.params}
    assert p["a"].type.kind == TypeKind.ARRAY and p["b"].type.kind == TypeKind.ARRAY
    assert p["c"].type.kind == TypeKind.ARRAY and p["d"].type.kind == TypeKind.ARRAY
    assert p["e"].type.kind == TypeKind.OBJECT and p["m"].type.fields[0].name == "q"
    assert p["bm"].type.kind == TypeKind.ANY and p["u"].type.kind == TypeKind.ANY
    assert p["lit"].type.enum_values == ("x",) and not p["lit"].required
    assert p["two"].type.enum_values == ("a", "b")
    assert t.returns.kind == TypeKind.STRING


def test_defaults_are_made_plain():
    @dataclasses.dataclass
    class D:
        a: int = 1

    def g(e: Mode = Mode.A, t: tuple = (1, 2), dd: dict = None, dc: D = D()) -> None:  # noqa: B008
        pass

    with pytest.warns(UserWarning, match="'D' has no IR type"):  # D is local; its default still converts
        p = {x.name: x.default for x in tool_from_callable(g).params}
    assert p == {"e": 1, "t": [1, 2], "dd": None, "dc": {"a": 1}}
