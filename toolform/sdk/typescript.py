"""TypeScript declarations to the canonical IR.

A small hand-written parser for the declaration subset agents use. It needs no
Node and no TypeScript compiler.

Supported: ``function``, ``declare function``, ``export function`` and
``export declare function``, each ending in ``;`` or a body (the body is
skipped by brace matching); a JSDoc block directly above (the first text is
the description, ``@param name text`` describes a parameter, ``@returns text``
the result); parameter types ``string``, ``number`` (``NUMBER``, since
TypeScript has no integer type), ``boolean``, ``any`` and ``unknown``
(``ANY``), ``null``, ``T[]``, ``Array<T>``, string or number literal unions
(``ENUM``), other unions (``UNION``), ``T | null`` or ``T | undefined`` or
``name?:`` (optional), inline object types ``{ a: string; b?: number }``,
named ``interface X {...}`` and ``type X = ...`` referenced by name, and
``Record<string, T>`` (an open ``OBJECT``).

A function with exactly one parameter whose type is an object and whose name
is ``args``, ``params``, ``input`` or ``options`` (or a destructured object) is
flattened: the object's fields become the tool's parameters.

Not supported, each raising :class:`LoaderError` with the line number:
generics on functions, classes, overloads, ``enum`` declarations, rest
parameters and types that are not declared in the file (imported types).
"""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..ir import Constraints, ParamIR, ToolIR, TypeIR, TypeKind
from .errors import LoaderError

# A JSDoc @param line: the tag, an optional {type}, the name (maybe [optional] or =default), the text.
_JSDOC_PARAM = re.compile(
    r"@(param|arg|argument)\s+(?:\{[^}]*\}\s*)?(\[?[A-Za-z_$][\w$.]*(?:=[^\]]*)?\]?)\s*-?\s*(.*)$"
)

FLATTEN_NAMES = ("args", "params", "input", "options")

_STATEMENT_WORDS = {
    "export",
    "declare",
    "function",
    "interface",
    "type",
    "const",
    "let",
    "var",
    "class",
    "enum",
    "import",
    "abstract",
    "namespace",
    "module",
    "async",
    "default",
}


@dataclass
class _Tok:
    kind: str  # ident | string | number | punct | doc
    value: str
    pos: int
    nl_before: bool


_PUNCT2 = ("=>", "...", "?.")


def _tokenize(src: str, source: str, line_of) -> list[_Tok]:
    toks: list[_Tok] = []
    i, n = 0, len(src)
    nl = True
    while i < n:
        ch = src[i]
        if ch in " \t\r":
            i += 1
            continue
        if ch == "\n":
            nl = True
            i += 1
            continue
        if src.startswith("/**", i) and not src.startswith("/**/", i):
            j = src.find("*/", i + 3)
            if j < 0:
                raise LoaderError("unclosed JSDoc comment", source=source, line=line_of(i))
            toks.append(_Tok("doc", src[i : j + 2], i, nl))
            nl = False
            i = j + 2
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise LoaderError("unclosed comment", source=source, line=line_of(i))
            i = j + 2
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch in "'\"`":
            j = i + 1
            while j < n and src[j] != ch:
                if src[j] == "\\":
                    j += 1
                j += 1
            if j >= n:
                raise LoaderError("unclosed string", source=source, line=line_of(i))
            toks.append(_Tok("string", src[i + 1 : j], i, nl))
            nl = False
            i = j + 1
            continue
        m = re.match(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", src[i : i + 64])
        if m and (ch.isdigit()):
            toks.append(_Tok("number", m.group(0), i, nl))
            nl = False
            i += len(m.group(0))
            continue
        m = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", src[i : i + 256])
        if m:
            toks.append(_Tok("ident", m.group(0), i, nl))
            nl = False
            i += len(m.group(0))
            continue
        for p in _PUNCT2:
            if src.startswith(p, i):
                toks.append(_Tok("punct", p, i, nl))
                nl = False
                i += len(p)
                break
        else:
            toks.append(_Tok("punct", ch, i, nl))
            nl = False
            i += 1
    return toks


@dataclass
class _Doc:
    description: str
    params: dict[str, str]
    returns: str


def _parse_jsdoc(text: str) -> _Doc:
    body = text[3:-2] if text.startswith("/**") else text
    # A one-line block can carry its tags inline: /** Doc. @param a the a */
    body = re.sub(r"[ \t]+@(?=(?:param|arg|argument|returns?)\b)", "\n@", body)
    lines = []
    for raw in body.splitlines():
        s = raw.strip()
        if s.startswith("*"):
            s = s[1:]
            if s.startswith(" "):
                s = s[1:]
        lines.append(s.rstrip())
    desc: list[str] = []
    params: dict[str, str] = {}
    returns: list[str] = []
    current: tuple[str, str] | None = None  # ("param", name) | ("returns", "")
    for line in lines:
        s = line.strip()
        if s.startswith("@"):
            m = _JSDOC_PARAM.match(s)
            if m:
                name = m.group(2).strip("[]").split("=")[0]
                params[name] = m.group(3).strip()
                current = ("param", name)
                continue
            m = re.match(r"@(returns?)\s+(?:\{[^}]*\}\s*)?-?\s*(.*)$", s)
            if m:
                returns.append(m.group(2).strip())
                current = ("returns", "")
                continue
            current = ("other", "")
            continue
        if current is None:
            desc.append(s)
        elif current[0] == "param" and s:
            params[current[1]] = (params[current[1]] + " " + s).strip()
        elif current[0] == "returns" and s:
            returns.append(s)
    paragraphs: list[list[str]] = [[]]
    for s in desc:
        if s:
            paragraphs[-1].append(s)
        elif paragraphs[-1]:
            paragraphs.append([])
    description = " ".join(" ".join(p) for p in paragraphs if p)
    return _Doc(description=description, params=params, returns=" ".join(r for r in returns if r))


@dataclass
class _T:
    """A parsed type: an IR type, a literal, or null, with a nullable flag."""

    kind: str  # ir | lit | null
    ir: TypeIR | None = None
    value: Any = None
    nullable: bool = False


class _Parser:
    def __init__(self, src: str, source: str) -> None:
        self.src = src
        self.source = source
        self.newlines = [i for i, c in enumerate(src) if c == "\n"]
        self.toks = _tokenize(src, source, self.line_of)
        self.i = 0
        self.interfaces: dict[str, tuple[int, int, list[str]]] = {}  # name -> (start, end, extends)
        self.aliases: dict[str, tuple[int, int]] = {}
        self.resolving: set[str] = set()
        self.cache: dict[str, _T] = {}

    # ------------------------------------------------------------ helpers
    def line_of(self, pos: int) -> int:
        return bisect.bisect_right(self.newlines, pos - 1) + 1 if pos > 0 else 1

    def err(self, msg: str, tok: _Tok | None = None) -> LoaderError:
        pos = tok.pos if tok is not None else (self.toks[self.i].pos if self.i < len(self.toks) else len(self.src))
        return LoaderError(msg, source=self.source, line=self.line_of(pos))

    def peek(self, k: int = 0) -> _Tok | None:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def kind_at(self, k: int = 0) -> str | None:
        t = self.peek(k)
        return t.kind if t is not None else None

    def value_at(self, k: int = 0) -> str | None:
        t = self.peek(k)
        return t.value if t is not None else None

    def at(self, value: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t is not None and t.kind in ("punct", "ident") and t.value == value

    def take(self) -> _Tok:
        if self.i >= len(self.toks):
            raise self.err("unexpected end of input")
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, value: str) -> _Tok:
        t = self.peek()
        if t is None or t.value != value or t.kind not in ("punct", "ident"):
            raise self.err(f"expected {value!r}, found {t.value if t else 'end of input'!r}", t)
        return self.take()

    def skip_docs(self) -> _Doc | None:
        doc = None
        while self.kind_at() == "doc":
            doc = _parse_jsdoc(self.take().value)
        return doc

    def match_close(self, open_ch: str, close_ch: str) -> int:
        """With the current token on ``open_ch``, return the index just past its match."""
        depth = 0
        j = self.i
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == "punct":
                if t.value == open_ch:
                    depth += 1
                elif t.value == close_ch:
                    depth -= 1
                    if depth == 0:
                        return j + 1
            j += 1
        raise self.err(f"unbalanced {open_ch!r}", self.peek())

    def skip_statement(self) -> None:
        """Skip to the end of a statement this parser does not model."""
        depth = 0
        first = True
        while self.i < len(self.toks):
            t = self.toks[self.i]
            if (
                not first
                and depth == 0
                and t.nl_before
                and (t.kind == "doc" or (t.kind == "ident" and t.value in _STATEMENT_WORDS))
            ):
                return
            first = False
            if t.kind == "punct":
                if t.value in "({[":
                    depth += 1
                elif t.value in ")}]":
                    depth -= 1
                    if depth == 0 and t.value == "}":
                        self.i += 1
                        if self.at(";"):
                            self.i += 1
                        return
                elif t.value == ";" and depth <= 0:
                    self.i += 1
                    return
            self.i += 1

    # -------------------------------------------------------- first pass
    def collect(self) -> list[tuple[int, _Doc | None]]:
        """Record interfaces and aliases; return the start index of every function with its JSDoc."""
        functions: list[tuple[int, _Doc | None]] = []
        while self.i < len(self.toks):
            doc = self.skip_docs()
            if self.i >= len(self.toks):
                break
            while self.kind_at() == "ident" and self.value_at() in ("export", "declare", "default", "async"):
                self.take()
            t = self.peek()
            if t is None:
                break
            if t.kind == "ident" and t.value == "function":
                start = self.i
                functions.append((start, doc))
                self.take()
                if self.at("*"):
                    self.take()
                name_tok = self.take()
                if self.at("<"):
                    raise self.err(f"function {name_tok.value!r}: generic functions are not supported", name_tok)
                if not self.at("("):
                    raise self.err(f"function {name_tok.value!r}: expected a parameter list", name_tok)
                self.i = self.match_close("(", ")")
                if self.at(":"):
                    self.take()
                    self.parse_type(lazy=True)
                if self.at("{"):
                    self.i = self.match_close("{", "}")
                elif self.at(";"):
                    self.take()
                continue
            if t.kind == "ident" and t.value == "interface":
                self.take()
                name_tok = self.take()
                if self.at("<"):
                    raise self.err(f"interface {name_tok.value!r}: generic interfaces are not supported", name_tok)
                extends: list[str] = []
                if self.at("extends"):
                    self.take()
                    while not self.at("{"):
                        tok = self.take()
                        if tok.kind == "ident":
                            extends.append(tok.value)
                start = self.i
                self.i = self.match_close("{", "}")
                self.interfaces[name_tok.value] = (start, self.i, extends)
                continue
            if (
                t.kind == "ident"
                and t.value == "type"
                and self.kind_at(1) == "ident"
                and (self.at("=", 2) or self.at("<", 2))
            ):
                self.take()
                name_tok = self.take()
                if self.at("<"):
                    raise self.err(f"type {name_tok.value!r}: generic type aliases are not supported", name_tok)
                self.expect("=")
                start = self.i
                self.parse_type(lazy=True)
                self.aliases[name_tok.value] = (start, self.i)
                if self.at(";"):
                    self.take()
                continue
            if t.kind == "ident" and t.value in ("class", "abstract"):
                raise self.err("classes are not supported; declare each tool as a function", t)
            if t.kind == "ident" and (t.value == "enum" or (t.value == "const" and self.at("enum", 1))):
                raise self.err("enum declarations are not supported; use a union of string literals", t)
            self.skip_statement()
        return functions

    # --------------------------------------------------------------- types
    def parse_type(self, lazy: bool = False) -> _T:
        """Parse one type expression at the cursor. ``lazy`` only skips it."""
        if self.at("|") or self.at("&"):
            self.take()
        members = [self.parse_intersection(lazy)]
        while self.at("|"):
            self.take()
            members.append(self.parse_intersection(lazy))
        if lazy:
            return _T("ir", TypeIR(kind=TypeKind.ANY))
        return self.combine(members)

    def parse_intersection(self, lazy: bool) -> _T:
        parts = [self.parse_postfix(lazy)]
        while self.at("&"):
            self.take()
            parts.append(self.parse_postfix(lazy))
        if lazy or len(parts) == 1:
            return parts[0]
        fields: list[ParamIR] = []
        for p in parts:
            if p.kind == "ir" and p.ir is not None and p.ir.kind == TypeKind.OBJECT:
                fields.extend(p.ir.fields)
            else:
                return _T("ir", TypeIR(kind=TypeKind.ANY))
        return _T("ir", TypeIR(kind=TypeKind.OBJECT, fields=tuple(fields)))

    def parse_postfix(self, lazy: bool) -> _T:
        t = self.parse_primary(lazy)
        while self.at("[") and self.at("]", 1):
            self.take()
            self.take()
            if not lazy:
                t = _T("ir", TypeIR(kind=TypeKind.ARRAY, item=self.to_ir(t)), nullable=False)
        return t

    def to_ir(self, t: _T) -> TypeIR:
        if t.kind == "lit":
            return TypeIR(kind=TypeKind.ENUM, enum_values=(t.value,), base=_lit_base([t.value]))
        if t.kind == "null":
            return TypeIR(kind=TypeKind.NULL)
        return t.ir or TypeIR(kind=TypeKind.ANY)

    def combine(self, members: list[_T]) -> _T:
        nullable = any(m.kind == "null" or m.nullable for m in members)
        rest = [m for m in members if m.kind != "null"]
        if not rest:
            return _T("ir", TypeIR(kind=TypeKind.NULL))
        if all(m.kind == "lit" for m in rest):
            values = [m.value for m in rest]
            if len(values) == 2 and set(values) == {True, False}:
                return _T("ir", TypeIR(kind=TypeKind.BOOLEAN), nullable=nullable)
            return _T(
                "ir", TypeIR(kind=TypeKind.ENUM, enum_values=tuple(values), base=_lit_base(values)), nullable=nullable
            )
        if len(rest) == 1:
            return _T("ir", self.to_ir(rest[0]), nullable=nullable)
        return _T("ir", TypeIR(kind=TypeKind.UNION, union_of=tuple(self.to_ir(m) for m in rest)), nullable=nullable)

    def parse_primary(self, lazy: bool) -> _T:
        t = self.peek()
        if t is None:
            raise self.err("expected a type, found the end of input")
        if t.kind == "string":
            self.take()
            return _T("lit", value=t.value)
        if t.kind == "number" or (t.kind == "punct" and t.value == "-" and self.kind_at(1) == "number"):
            neg = t.value == "-"
            if neg:
                self.take()
            num = self.take().value
            v: Any = float(num) if any(c in num for c in ".eE") else int(num)
            return _T("lit", value=-v if neg else v)
        if t.kind == "punct" and t.value == "{":
            if lazy:
                self.i = self.match_close("{", "}")
                return _T("ir")
            end = self.match_close("{", "}")
            self.take()
            fields, open_obj = self.parse_fields(end - 1)
            self.i = end
            return _T("ir", TypeIR(kind=TypeKind.OBJECT, fields=tuple(fields)))
        if t.kind == "punct" and t.value == "(":
            end = self.match_close("(", ")")
            if end < len(self.toks) and self.toks[end].value == "=>":
                self.i = end + 1
                self.parse_type(lazy=True)
                return _T("ir", TypeIR(kind=TypeKind.ANY))
            self.take()
            inner = self.parse_type(lazy)
            self.expect(")")
            return inner
        if t.kind == "punct" and t.value == "[":
            end = self.match_close("[", "]")
            self.take()
            items: list[_T] = []
            while self.i < end - 1:
                items.append(self.parse_type(lazy))
                if self.at(","):
                    self.take()
            self.i = end
            if lazy:
                return _T("ir")
            irs = [self.to_ir(x) for x in items]
            uniq = {json.dumps(x.to_dict(), sort_keys=True): x for x in irs}
            item = (
                irs[0]
                if len(uniq) == 1
                else (TypeIR(kind=TypeKind.UNION, union_of=tuple(uniq.values())) if irs else None)
            )
            return _T(
                "ir",
                TypeIR(kind=TypeKind.ARRAY, item=item, constraints=Constraints(min_items=len(irs), max_items=len(irs))),
            )
        if t.kind != "ident":
            raise self.err(f"unexpected {t.value!r} in a type", t)
        self.take()
        word = t.value
        if word == "readonly" or word == "keyof" or word == "typeof":
            inner = self.parse_postfix(lazy)
            return inner if word == "readonly" else _T("ir", TypeIR(kind=TypeKind.STRING))
        if word in (
            "Array",
            "ReadonlyArray",
            "Set",
            "Promise",
            "Partial",
            "Readonly",
            "Required",
            "Record",
            "Map",
        ) and self.at("<"):
            self.take()
            args = [self.parse_type(lazy)]
            while self.at(","):
                self.take()
                args.append(self.parse_type(lazy))
            self.expect(">")
            if lazy:
                return _T("ir")
            if word in ("Array", "ReadonlyArray", "Set"):
                return _T("ir", TypeIR(kind=TypeKind.ARRAY, item=self.to_ir(args[0])))
            if word in ("Record", "Map"):
                return _T("ir", TypeIR(kind=TypeKind.OBJECT))
            inner = args[0]
            if word == "Partial" and inner.kind == "ir" and inner.ir is not None and inner.ir.fields:
                return _T("ir", replace(inner.ir, fields=tuple(replace(f, required=False) for f in inner.ir.fields)))
            return inner
        if lazy:
            return _T("ir")
        simple = {
            "string": TypeKind.STRING,
            "number": TypeKind.NUMBER,
            "boolean": TypeKind.BOOLEAN,
            "any": TypeKind.ANY,
            "unknown": TypeKind.ANY,
            "object": TypeKind.OBJECT,
            "Date": TypeKind.STRING,
            "bigint": TypeKind.INTEGER,
            "integer": TypeKind.INTEGER,
            "Object": TypeKind.OBJECT,
            "String": TypeKind.STRING,
            "Number": TypeKind.NUMBER,
            "Boolean": TypeKind.BOOLEAN,
        }
        if word in simple:
            ir = TypeIR(
                kind=simple[word], constraints=Constraints(format="date-time") if word == "Date" else Constraints()
            )
            return _T("ir", ir)
        if word in ("null", "undefined", "void", "never"):
            return _T("null")
        if word == "true":
            return _T("lit", value=True)
        if word == "false":
            return _T("lit", value=False)
        return self.named(word, t)

    def named(self, word: str, tok: _Tok) -> _T:
        if word in self.cache:
            return self.cache[word]
        if word in self.resolving:
            return _T("ir", TypeIR(kind=TypeKind.OBJECT))  # a recursive type stops here
        if word in self.interfaces:
            start, end, extends = self.interfaces[word]
            self.resolving.add(word)
            saved = self.i
            fields: list[ParamIR] = []
            for base in extends:
                b = self.named(base, tok)
                if b.ir is not None:
                    fields.extend(b.ir.fields)
            self.i = start + 1
            own, _ = self.parse_fields(end - 1)
            names = {f.name for f in own}
            fields = [f for f in fields if f.name not in names] + own
            self.i = saved
            self.resolving.discard(word)
            out = _T("ir", TypeIR(kind=TypeKind.OBJECT, fields=tuple(fields)))
            self.cache[word] = out
            return out
        if word in self.aliases:
            start, end = self.aliases[word]
            self.resolving.add(word)
            saved = self.i
            self.i = start
            out = self.parse_type()
            self.i = saved
            self.resolving.discard(word)
            self.cache[word] = out
            return out
        raise self.err(f"unknown type {word!r}; declare it in the file (imported types are not supported)", tok)

    def parse_fields(self, end: int) -> tuple[list[ParamIR], bool]:
        """Fields of an object type from the cursor up to token index ``end`` (the closing brace)."""
        fields: list[ParamIR] = []
        open_obj = False
        while self.i < end:
            doc = self.skip_docs()
            if self.i >= end:
                break
            if self.at(";") or self.at(","):
                self.take()
                continue
            if self.at("readonly") and self.peek(1) is not None and self.value_at(1) not in (":", "?"):
                self.take()
            if self.at("["):
                close = self.match_close("[", "]")
                self.i = close
                if self.at(":"):
                    self.take()
                    self.parse_type(lazy=True)
                open_obj = True
                continue
            key_tok = self.take()
            if key_tok.kind not in ("ident", "string", "number"):
                raise self.err(f"unexpected {key_tok.value!r} in an object type", key_tok)
            optional = False
            if self.at("?"):
                self.take()
                optional = True
            if self.at("("):  # a method signature: not a data field
                self.i = self.match_close("(", ")")
                if self.at(":"):
                    self.take()
                    self.parse_type(lazy=True)
                continue
            if self.at(":"):
                self.take()
                t = self.parse_type()
            else:
                t = _T("ir", TypeIR(kind=TypeKind.ANY))
            fields.append(
                ParamIR(
                    name=key_tok.value,
                    type=self.to_ir(t),
                    description=doc.description if doc else "",
                    required=not optional and not t.nullable,
                )
            )
        return fields, open_obj

    # ----------------------------------------------------------- functions
    def parse_default(self) -> Any:
        start = self.i
        depth = 0
        while self.i < len(self.toks):
            t = self.toks[self.i]
            if t.kind == "punct" and t.value in "([{":
                depth += 1
            elif t.kind == "punct" and t.value in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif t.kind == "punct" and t.value == "," and depth == 0:
                break
            self.i += 1
        toks = self.toks[start : self.i]
        if len(toks) == 1:
            t = toks[0]
            if t.kind == "string":
                return t.value
            if t.kind == "number":
                return float(t.value) if any(c in t.value for c in ".eE") else int(t.value)
            if t.kind == "ident" and t.value in ("true", "false"):
                return t.value == "true"
        if len(toks) == 2 and toks[0].value == "-" and toks[1].kind == "number":
            v = toks[1].value
            return -(float(v) if "." in v else int(v))
        if len(toks) == 2 and toks[0].value == "[" and toks[1].value == "]":
            return []
        return None

    def parse_function(self, start: int, doc: _Doc | None) -> ToolIR:
        self.i = start
        self.expect("function")
        if self.at("*"):
            self.take()
        name_tok = self.take()
        name = name_tok.value
        end = self.match_close("(", ")")
        self.take()
        params: list[ParamIR] = []
        destructured = False
        while self.i < end - 1:
            pdoc = self.skip_docs()
            if self.at(","):
                self.take()
                continue
            if self.at("..."):
                raise self.err(f"function {name!r}: rest parameters are not supported", self.peek())
            if self.at("{"):
                self.i = self.match_close("{", "}")
                pname = "args"
                destructured = True
            else:
                ptok = self.take()
                if ptok.kind != "ident":
                    raise self.err(f"function {name!r}: unexpected {ptok.value!r} in the parameters", ptok)
                pname = ptok.value
            if pname == "this":
                if self.at(":"):
                    self.take()
                    self.parse_type(lazy=True)
                continue
            optional = False
            if self.at("?"):
                self.take()
                optional = True
            t = _T("ir", TypeIR(kind=TypeKind.ANY))
            if self.at(":"):
                self.take()
                t = self.parse_type()
            default = None
            if self.at("="):
                self.take()
                default = self.parse_default()
                optional = True
            desc = ""
            if doc and pname in doc.params:
                desc = doc.params[pname]
            elif pdoc:
                desc = pdoc.description
            params.append(
                ParamIR(
                    name=pname,
                    type=self.to_ir(t),
                    description=desc,
                    required=not optional and not t.nullable,
                    default=default,
                )
            )
        self.i = end
        returns = None
        if self.at(":"):
            self.take()
            try:
                rt = self.parse_type()
                ir = self.to_ir(rt)
                if ir.kind not in (TypeKind.NULL, TypeKind.ANY):
                    returns = ir
            except LoaderError:
                returns = None
        if (
            len(params) == 1
            and params[0].type.kind == TypeKind.OBJECT
            and params[0].type.fields
            and (destructured or params[0].name in FLATTEN_NAMES)
        ):
            outer = params[0].name
            flat = []
            for f in params[0].type.fields:
                d = f.description
                if doc:
                    d = doc.params.get(f"{outer}.{f.name}", doc.params.get(f.name, d)) or d
                flat.append(replace(f, description=d))
            params = flat
        return ToolIR(
            name=name,
            description=doc.description if doc else "",
            params=tuple(params),
            returns=returns,
            returns_description=doc.returns if doc else "",
            domain="user",
            category="user",
            origin="user",
        )


def _lit_base(values: list[Any]) -> TypeKind:
    if values and all(isinstance(v, bool) for v in values):
        return TypeKind.BOOLEAN
    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return TypeKind.NUMBER
    return TypeKind.STRING


def from_typescript(source: str | Path) -> list[ToolIR]:
    """Tools from a ``.ts`` / ``.d.ts`` file or TypeScript source text."""
    label = "inline input"
    text: str
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and source.strip().endswith(".ts")):
        p = Path(source).expanduser()
        if not p.is_file():
            raise LoaderError("no such file", source=str(source))
        label = str(p)
        text = p.read_text(encoding="utf-8")
    else:
        text = str(source)
    parser = _Parser(text, label)
    functions = parser.collect()
    tools: list[ToolIR] = []
    seen: dict[str, int] = {}
    for start, doc in functions:
        name_tok = parser.toks[start + 1] if parser.toks[start + 1].value != "*" else parser.toks[start + 2]
        if name_tok.value in seen:
            raise LoaderError(
                f"function {name_tok.value!r} is declared more than once (overloads are not supported)",
                source=label,
                line=parser.line_of(name_tok.pos),
            )
        seen[name_tok.value] = start
        tools.append(parser.parse_function(start, doc))
    if not tools:
        raise LoaderError("no function declarations found", source=label)
    return tools


__all__ = ["FLATTEN_NAMES", "from_typescript"]
