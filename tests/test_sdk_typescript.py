"""TypeScript declarations to the IR."""

from __future__ import annotations

import pytest

from toolform.ir import TypeKind
from toolform.sdk import LoaderError, Toolset
from toolform.sdk.typescript import from_typescript


def test_fixture_file(fixtures_dir):
    ts = Toolset.from_typescript(fixtures_dir / "tools.d.ts")
    assert ts.names() == ["open_ticket", "close_ticket", "search_tickets"]
    ot = ts.get("open_ticket")
    assert ot.description == "Open a new ticket."
    assert ot.returns_description == "The new ticket's id."
    p = {x.name: x for x in ot.params}
    assert p["title"].required and p["title"].description == "Short summary of the problem."
    assert p["priority"].type.enum_values == ("low", "normal", "high") and p["priority"].default == "normal"
    assert not p["priority"].required
    assert p["assignee"].type.kind == TypeKind.OBJECT and not p["assignee"].required
    fields = {f.name: f for f in p["assignee"].type.fields}
    assert fields["login"].required and fields["login"].description == "Login name." and not fields["name"].required
    assert p["labels"].type.kind == TypeKind.ARRAY and p["labels"].type.item.kind == TypeKind.STRING


def test_single_argument_is_flattened(fixtures_dir):
    ct = Toolset.from_typescript(fixtures_dir / "tools.d.ts").get("close_ticket")
    p = {x.name: x for x in ct.params}
    assert list(p) == ["ticket_id", "resolution", "note"]
    assert p["ticket_id"].type.kind == TypeKind.NUMBER
    assert p["resolution"].type.enum_values == ("fixed", "wontfix", "duplicate")
    assert not p["note"].required and p["note"].type.kind == TypeKind.STRING


def test_record_and_generic_array(fixtures_dir):
    st = Toolset.from_typescript(str(fixtures_dir / "tools.d.ts")).get("search_tickets")
    p = {x.name: x for x in st.params}
    assert p["filters"].type.kind == TypeKind.OBJECT and p["filters"].type.fields == ()
    assert st.returns.kind == TypeKind.ARRAY


@pytest.mark.parametrize(
    "src,check",
    [
        (
            "function f(a: string, b: number, c: boolean, d: any, e: unknown, n: null): void;",
            lambda t: (
                [p.type.kind for p in t.params]
                == [TypeKind.STRING, TypeKind.NUMBER, TypeKind.BOOLEAN, TypeKind.ANY, TypeKind.ANY, TypeKind.NULL]
            ),
        ),
        (
            "export function f(a: Array<number>, b: string[][]): void { }",
            lambda t: t.params[0].type.item.kind == TypeKind.NUMBER and t.params[1].type.item.kind == TypeKind.ARRAY,
        ),
        (
            "declare function f(a: 1 | 2 | 3, b: string | number, c?: string | undefined): void;",
            lambda t: (
                t.params[0].type.enum_values == (1, 2, 3)
                and t.params[1].type.kind == TypeKind.UNION
                and not t.params[2].required
            ),
        ),
        (
            "function f(o: { a: string, b?: number; c: { d: boolean } }): void;",
            lambda t: t.params[0].name == "o" and [f.name for f in t.params[0].type.fields] == ["a", "b", "c"],
        ),
        ("function f(input: { a: string }): void;", lambda t: [p.name for p in t.params] == ["a"]),
        ("function f({ a, b }: { a: string; b: number }): void;", lambda t: [p.name for p in t.params] == ["a", "b"]),
        (
            "function f(x: number = -2, y = true, z: string[] = []): void;",
            lambda t: [p.default for p in t.params] == [-2, True, []] and not any(p.required for p in t.params),
        ),
        (
            "interface A { x: string }\ninterface B extends A { y: number }\nfunction f(b: B): void;",
            lambda t: [f.name for f in t.params[0].type.fields] == ["x", "y"],
        ),
        (
            "type T = { a: string };\nfunction f(t: T, flag: true | false): void;",
            lambda t: t.params[0].type.fields[0].name == "a" and t.params[1].type.kind == TypeKind.BOOLEAN,
        ),
        (
            "/** Doc. @param a the a */\nfunction f(a: string): void;",
            lambda t: t.description == "Doc." and t.params[0].description == "the a",
        ),
    ],
)
def test_constructs(src, check):
    tools = from_typescript(src)
    assert check(tools[0])


def test_jsdoc_param_forms():
    src = """/**
 * Describe.
 *
 * Second paragraph.
 * @param {string} a - The a.
 * @param [b] The b,
 *   continued.
 * @return Something.
 */
function f(a: string, b?: number): string;"""
    t = from_typescript(src)[0]
    assert t.description == "Describe. Second paragraph."
    assert t.params[0].description == "The a." and t.params[1].description == "The b, continued."
    assert t.returns_description == "Something."


@pytest.mark.parametrize(
    "src,line,msg",
    [
        ("\nfunction f<T>(x: T): T;", 2, "generic"),
        ("class A {}", 1, "classes"),
        ("\n\nenum E { A }", 3, "enum"),
        ("const enum E { A }", 1, "enum"),
        ("function g(x: Foo): void;", 1, "unknown type 'Foo'"),
        ("function h(a: string): void;\nfunction h(b: number): void;", 2, "more than once"),
        ("function r(...xs: string[]): void;", 1, "rest"),
        ("interface I<T> { a: T }", 1, "generic"),
    ],
)
def test_unsupported_raise_with_line(src, line, msg):
    with pytest.raises(LoaderError, match=msg) as info:
        from_typescript(src)
    assert info.value.line == line


def test_other_statements_are_skipped():
    src = (
        "import { x } from 'y';\nexport const k = { a: 1 };\nlet z = () => { return 1; };\nfunction f(a: string): void;"
    )
    assert [t.name for t in from_typescript(src)] == ["f"]


def test_errors_on_empty_and_missing(tmp_path):
    with pytest.raises(LoaderError, match="no function"):
        from_typescript("interface A { x: string }")
    with pytest.raises(LoaderError, match="no such file"):
        from_typescript(str(tmp_path / "none.ts"))
    with pytest.raises(LoaderError, match="unclosed"):
        from_typescript("/** never closed\nfunction f(): void;")


@pytest.mark.parametrize(
    "src,check",
    [
        (
            "type A = { a: string };\ntype B = { b: number };\nfunction f(x: A & B): void;",
            lambda t: [f.name for f in t.params[0].type.fields] == ["a", "b"],
        ),
        ("function f(x: string & number): void;", lambda t: t.params[0].type.kind == TypeKind.ANY),
        (
            "function f(x: (string | number)[]): void;",
            lambda t: t.params[0].type.kind == TypeKind.ARRAY and t.params[0].type.item.kind == TypeKind.UNION,
        ),
        (
            "function f(x: [string, number], y: [string, string]): void;",
            lambda t: (
                t.params[0].type.item.kind == TypeKind.UNION
                and t.params[1].type.item.kind == TypeKind.STRING
                and t.params[0].type.constraints.min_items == 2
            ),
        ),
        (
            "interface A { a: string; b: number }\nfunction f(x: Partial<A>, y: Readonly<A>): void;",
            lambda t: not any(f.required for f in t.params[0].type.fields) and t.params[1].type.fields[0].required,
        ),
        (
            "function f(cb: (x: string) => void, d: Date, k: keyof string, big: bigint): void;",
            lambda t: (
                [p.type.kind for p in t.params] == [TypeKind.ANY, TypeKind.STRING, TypeKind.STRING, TypeKind.INTEGER]
                and t.params[1].type.constraints.format == "date-time"
            ),
        ),
        (
            "function f(o: { readonly a: string; [key: string]: any; m(): void; 'q': number }): void;",
            lambda t: [f.name for f in t.params[0].type.fields] == ["a", "q"],
        ),
        (
            "function f(x: -1 | 2.5, s: Set<string>, m: Map<string, number>): void;",
            lambda t: (
                t.params[0].type.enum_values == (-1, 2.5)
                and t.params[1].type.kind == TypeKind.ARRAY
                and t.params[2].type.kind == TypeKind.OBJECT
            ),
        ),
        ("function f(this: Window, a: string): void;", lambda t: [p.name for p in t.params] == ["a"]),
        (
            "function f(a: readonly string[], b: never | string): void;",
            lambda t: t.params[0].type.kind == TypeKind.ARRAY and not t.params[1].required,
        ),
        (
            "interface Node { next?: Node; v: string }\nfunction f(n: Node): void;",
            lambda t: t.params[0].type.fields[0].type.kind == TypeKind.OBJECT,
        ),
        (
            "function f(a = 'x', b = 1.5, c = -3, d = null, e = foo()): void;",
            lambda t: [p.default for p in t.params] == ["x", 1.5, -3, None, None],
        ),
        ("async function f(a: string): Promise<void> { await x; }", lambda t: t.returns is None),
        ("function* gen(a: string): void {}", lambda t: t.name == "gen"),
        ("export default function f(a: string): void {}", lambda t: t.name == "f"),
        (
            "function f(a: object, b: true): string | null;",
            lambda t: (
                t.params[0].type.kind == TypeKind.OBJECT
                and t.params[1].type.enum_values == (True,)
                and t.returns.kind == TypeKind.STRING
            ),
        ),
    ],
)
def test_more_constructs(src, check):
    assert check(from_typescript(src)[0])


@pytest.mark.parametrize(
    "src,msg",
    [
        ("function f(a: string", "unbalanced"),
        ("function f(: string): void;", "unexpected"),
        ("function f(a: { 1+ }): void;", "unexpected"),
        ("function f(a: 'unclosed): void;", "unclosed string"),
        ("function f(a: ;): void;", "unexpected"),
        ("function f;", "parameter list"),
        ("type T<X> = X;\nfunction f(a: string): void;", "generic"),
    ],
)
def test_malformed_input(src, msg):
    with pytest.raises(LoaderError, match=msg):
        from_typescript(src)
