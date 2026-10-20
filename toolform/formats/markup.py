"""XML and HTML-shaped tool descriptions.

XML matters here for a specific reason: several vendors have shipped
XML-tagged tool blocks in system prompts, and models are often post-trained to
respond inside XML tags. So this family lets us ask whether the *presentation*
tag style and the *response* tag style interact.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register


def _x(s: str) -> str:
    return escape(str(s))


def _type_attr(t: TypeIR) -> str:
    return t.kind.value


def _param_xml(p: ParamIR, opts: RenderOptions, indent: str) -> list[str]:
    out = [f'{indent}<parameter name="{_x(p.name)}" type="{_type_attr(p.type)}" required="{str(p.required).lower()}">']
    if opts.descriptions and p.description:
        out.append(f"{indent}  <description>{_x(p.description)}</description>")
    if p.type.kind == TypeKind.ENUM:
        out.append(f"{indent}  <enum>" + ", ".join(_x(v) for v in p.type.enum_values) + "</enum>")
    if p.type.kind == TypeKind.ARRAY and p.type.item is not None:
        out.append(f'{indent}  <items type="{_type_attr(p.type.item)}"/>')
    if p.type.kind == TypeKind.OBJECT and p.type.fields:
        out.append(f"{indent}  <fields>")
        for f in p.type.fields:
            out.extend(_param_xml(f, opts, indent + "    "))
        out.append(f"{indent}  </fields>")
    if opts.defaults and p.default is not None:
        out.append(f"{indent}  <default>{_x(p.default)}</default>")
    out.append(f"{indent}</parameter>")
    return out


@register
class XMLTools(SchemaRenderer):
    meta = FormatMeta(
        id="xml_schema",
        name="XML tool descriptions",
        family="markup",
        description=(
            "`<tool><name/><description/><parameters/></tool>` blocks. The "
            "shape several vendors have used for prompt-level tool listings."
        ),
        default_protocol="xml_call",
        real_world_origin="Anthropic legacy tool_description blocks; many agent prompts",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["<tools>"]
        for t in tools:
            out.append("  <tool>")
            out.append(f"    <name>{_x(t.name)}</name>")
            if opts.descriptions and t.description:
                out.append(f"    <description>{_x(t.description)}</description>")
            out.append("    <parameters>")
            for p in t.params:
                out.extend(_param_xml(p, opts, "      "))
            out.append("    </parameters>")
            if opts.returns and t.returns_description:
                out.append(f"    <returns>{_x(t.returns_description)}</returns>")
            out.append("  </tool>")
        out.append("</tools>")
        return "\n".join(out)


@register
class XMLAttributes(SchemaRenderer):
    meta = FormatMeta(
        id="xml_attributes",
        name="XML with attribute-only parameters",
        family="markup",
        description=(
            "Everything moved into attributes so each parameter is one line. "
            "Same information as xml_schema at roughly half the tokens."
        ),
        default_protocol="xml_call",
        real_world_origin="XML attribute style",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["<tools>"]
        for t in tools:
            desc = f' desc="{_x(t.description)}"' if opts.descriptions and t.description else ""
            out.append(f'  <tool name="{_x(t.name)}"{desc}>')
            for p in t.params:
                bits = [f'name="{_x(p.name)}"', f'type="{_type_attr(p.type)}"']
                if p.required:
                    bits.append('required="true"')
                if p.type.kind == TypeKind.ENUM:
                    bits.append('values="' + "|".join(_x(v) for v in p.type.enum_values) + '"')
                if opts.descriptions and p.description:
                    bits.append(f'desc="{_x(p.description)}"')
                out.append("    <param " + " ".join(bits) + "/>")
            out.append("  </tool>")
        out.append("</tools>")
        return "\n".join(out)


@register
class XSDSchema(SchemaRenderer):
    meta = FormatMeta(
        id="xsd",
        name="XML Schema Definition (XSD)",
        family="markup",
        description=(
            "Formal XSD with complexType, xs:element minOccurs/maxOccurs and "
            "xs:restriction enumerations. The most verbose format in the study."
        ),
        default_protocol="xml_call",
        real_world_origin="W3C XML Schema",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ['<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">']
        for t in tools:
            out.append(f'  <xs:element name="{_x(t.name)}">')
            if opts.descriptions and t.description:
                out.append("    <xs:annotation>")
                out.append(f"      <xs:documentation>{_x(t.description)}</xs:documentation>")
                out.append("    </xs:annotation>")
            out.append("    <xs:complexType>")
            out.append("      <xs:sequence>")
            for p in t.params:
                occurs = "" if p.required else ' minOccurs="0"'
                if p.type.kind == TypeKind.ENUM:
                    out.append(f'        <xs:element name="{_x(p.name)}"{occurs}>')
                    out.append("          <xs:simpleType>")
                    out.append('            <xs:restriction base="xs:string">')
                    for v in p.type.enum_values:
                        out.append(f'              <xs:enumeration value="{_x(v)}"/>')
                    out.append("            </xs:restriction>")
                    out.append("          </xs:simpleType>")
                    out.append("        </xs:element>")
                else:
                    out.append(f'        <xs:element name="{_x(p.name)}" type="xs:{_xsd_type(p.type)}"{occurs}/>')
            out.append("      </xs:sequence>")
            out.append("    </xs:complexType>")
            out.append("  </xs:element>")
        out.append("</xs:schema>")
        return "\n".join(out)


def _xsd_type(t: TypeIR) -> str:
    return {
        TypeKind.STRING: "string",
        TypeKind.INTEGER: "integer",
        TypeKind.NUMBER: "decimal",
        TypeKind.BOOLEAN: "boolean",
        TypeKind.ARRAY: "string",
        TypeKind.OBJECT: "anyType",
    }.get(t.kind, "string")


@register
class HTMLForms(SchemaRenderer):
    meta = FormatMeta(
        id="html_forms",
        name="HTML forms (novel)",
        family="markup",
        description=(
            "Each tool as an HTML `<form>`: inputs with type, required, "
            "min/max, `<select><option>` for enums, `<label>` for descriptions. "
            "Web forms are exactly a typed argument interface, and models have "
            "seen billions of them."
        ),
        default_protocol="url_call",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(f'<form action="/{t.name}" method="post">')
            if opts.descriptions and t.description:
                out.append(f"  <legend>{_x(t.description)}</legend>")
            for p in t.params:
                lbl = f'  <label for="{_x(p.name)}">{_x(p.description or p.name)}</label>'
                out.append(lbl)
                if p.type.kind == TypeKind.ENUM:
                    out.append(f'  <select name="{_x(p.name)}"{" required" if p.required else ""}>')
                    for v in p.type.enum_values:
                        out.append(f'    <option value="{_x(v)}">{_x(v)}</option>')
                    out.append("  </select>")
                else:
                    bits = [f'name="{_x(p.name)}"', f'type="{_html_input(p.type)}"']
                    if p.required:
                        bits.append("required")
                    c = p.type.constraints
                    if opts.constraints:
                        if c.minimum is not None:
                            bits.append(f'min="{c.minimum}"')
                        if c.maximum is not None:
                            bits.append(f'max="{c.maximum}"')
                        if c.pattern:
                            bits.append(f'pattern="{_x(c.pattern)}"')
                    if opts.defaults and p.default is not None:
                        bits.append(f'value="{_x(p.default)}"')
                    out.append("  <input " + " ".join(bits) + ">")
            out.append('  <button type="submit">Run</button>')
            out.append("</form>")
            out.append("")
        return "\n".join(out).rstrip()


def _html_input(t: TypeIR) -> str:
    return {
        TypeKind.INTEGER: "number",
        TypeKind.NUMBER: "number",
        TypeKind.BOOLEAN: "checkbox",
    }.get(t.kind, "text")


@register
class MarkdownDocs(SchemaRenderer):
    meta = FormatMeta(
        id="markdown_docs",
        name="Markdown API documentation",
        family="markup",
        description=(
            "Human API docs: `## tool_name`, a prose paragraph, a bulleted "
            "parameter list with types, and a usage example. What a developer "
            "would actually read."
        ),
        default_protocol="json_object",
        real_world_origin="Standard API reference documentation",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["# Available tools", ""]
        for t in tools:
            out.append(f"## `{t.name}`")
            out.append("")
            if opts.descriptions and t.description:
                out.append(t.description)
                out.append("")
            if t.params:
                out.append("**Parameters**")
                out.append("")
                for p in t.params:
                    req = "required" if p.required else "optional"
                    line = f"- `{p.name}` (*{_md_type(p.type)}*, {req})"
                    if opts.descriptions and p.description:
                        line += f" — {p.description}"
                    if opts.defaults and p.default is not None:
                        line += f" Default: `{p.default}`."
                    out.append(line)
                    if p.type.kind == TypeKind.OBJECT and p.type.fields:
                        for f in p.type.fields:
                            fr = "required" if f.required else "optional"
                            sub = f"    - `{f.name}` (*{_md_type(f.type)}*, {fr})"
                            if opts.descriptions and f.description:
                                sub += f" — {f.description}"
                            out.append(sub)
                out.append("")
            if opts.returns and t.returns_description:
                out.append(f"**Returns** — {t.returns_description}")
                out.append("")
        return "\n".join(out).rstrip()


def _md_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"array of {_md_type(t.item)}" if t.item else "array"
    if t.kind == TypeKind.ENUM:
        return "one of " + ", ".join(f"`{v}`" for v in t.enum_values)
    if t.kind == TypeKind.UNION:
        return " or ".join(_md_type(u) for u in t.union_of)
    if t.kind == TypeKind.OBJECT:
        return "object"
    return t.kind.value


@register
class RestEndpoints(SchemaRenderer):
    meta = FormatMeta(
        id="rest_endpoints",
        name="REST endpoint listing",
        family="markup",
        description=(
            "`POST /tool_name` with a documented JSON body. Frames tools as HTTP endpoints rather than functions."
        ),
        default_protocol="url_call",
        real_world_origin="REST API documentation",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(f"POST /{t.name.replace('_', '-')}")
            if opts.descriptions and t.description:
                out.append(f"  Summary: {t.description}")
            out.append("  Body (application/json):")
            for p in t.params:
                req = "required" if p.required else "optional"
                line = f"    {p.name} : {_md_type(p.type)} [{req}]"
                if opts.descriptions and p.description:
                    line += f" - {p.description}"
                out.append(line)
            out.append("")
        return "\n".join(out).rstrip()


@register
class CurlExamples(SchemaRenderer):
    meta = FormatMeta(
        id="curl_examples",
        name="curl invocation examples (novel)",
        family="markup",
        description=(
            "Every tool shown only as a runnable `curl` command with a filled "
            "example body. There is no abstract schema at all — the model has "
            "to generalise from a concrete instance."
        ),
        default_protocol="json_object",
        novel=True,
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        import json as _json

        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"# {t.description}")
            body = {p.name: _example_value(p) for p in t.params if p.required}
            out.append(f"curl -X POST https://api.tools/{t.name} \\")
            out.append("  -H 'Content-Type: application/json' \\")
            out.append(f"  -d '{_json.dumps(body)}'")
            opt = [p.name for p in t.params if not p.required]
            if opt:
                out.append(f"# optional fields: {', '.join(opt)}")
            out.append("")
        return "\n".join(out).rstrip()


def _example_value(p: ParamIR):
    if p.example is not None:
        return p.example
    if p.default is not None:
        return p.default
    t = p.type
    if t.kind == TypeKind.ENUM and t.enum_values:
        return t.enum_values[0]
    if t.kind == TypeKind.INTEGER:
        return 1
    if t.kind == TypeKind.NUMBER:
        return 1.0
    if t.kind == TypeKind.BOOLEAN:
        return True
    if t.kind == TypeKind.ARRAY:
        return [_example_scalar(t.item)]
    if t.kind == TypeKind.OBJECT:
        return {f.name: _example_scalar(f.type) for f in t.fields}
    return f"<{p.name}>"


def _example_scalar(t: TypeIR | None):
    if t is None:
        return "value"
    if t.kind == TypeKind.INTEGER:
        return 1
    if t.kind == TypeKind.NUMBER:
        return 1.0
    if t.kind == TypeKind.BOOLEAN:
        return True
    if t.kind == TypeKind.ENUM and t.enum_values:
        return t.enum_values[0]
    return "value"
