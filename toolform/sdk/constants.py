"""Names and numbers the whole framework shares.

The eight core formats are the ones every statistical claim of the study is made
on, each with the protocol it was measured with. The five crossing protocols are
the ones the format by protocol experiment paired with every core format. The
three grading rules are the study's three graders, named as the framework names
them.
"""

from __future__ import annotations

#: The framework's version, and the package's: pyproject.toml reads it from here.
FRAMEWORK_VERSION = "0.0.1"

CORE_FORMATS: tuple[str, ...] = (
    "xml_schema",
    "natural_language",
    "python_stub",
    "json_schema_openai",
    "yaml_schema",
    "typescript",
    "markdown_table",
    "json_minimal",
)

CORE_FORMAT_LABELS: dict[str, str] = {
    "xml_schema": "XML",
    "natural_language": "natural language",
    "python_stub": "Python stub",
    "json_schema_openai": "JSON Schema",
    "yaml_schema": "YAML",
    "typescript": "TypeScript",
    "markdown_table": "Markdown table",
    "json_minimal": "minimal schema",
}

#: The default protocol each core format was measured with on the main grid.
CORE_DEFAULT_PROTOCOLS: dict[str, str] = {
    "xml_schema": "xml_call",
    "natural_language": "nl_intent",
    "python_stub": "python_call",
    "json_schema_openai": "json_object",
    "yaml_schema": "json_object",
    "typescript": "json_object",
    "markdown_table": "json_object",
    "json_minimal": "json_object",
}

CROSSING_PROTOCOLS: tuple[str, ...] = (
    "xml_call",
    "nl_intent",
    "json_object",
    "python_call",
    "tool_call_tags",
)

RULES: tuple[str, ...] = ("main", "symmetric", "as_written")

RULE_COLUMNS: dict[str, str] = {
    "main": "call_exact",
    "symmetric": "call_exact_symmetric",
    "as_written": "call_exact_as_written",
}

#: The four registered two-stage variants. The framework shows 129 study formats
#: and treats these as the catalogue module's two-stage modes.
TWO_STAGE_FORMATS: tuple[str, ...] = (
    "names_then_schema",
    "names_then_schema_v2",
    "names_desc_then_schema",
    "oracle_then_schema",
)

DEFAULT_PORT = 8765
STUDY_FORMAT_COUNT = 129
STUDY_PROTOCOL_COUNT = 31

#: Protocols whose parsers re-nest a flat argument under the main rule.
TEXT_PROTOCOLS: tuple[str, ...] = ("xml_call", "nl_intent")


def check_rule(rule: str) -> str:
    """Return ``rule`` if it is one of :data:`RULES`, else raise ``ValueError``."""
    if rule not in RULES:
        raise ValueError(f"unknown grading rule {rule!r}; use one of {', '.join(RULES)}")
    return rule


__all__ = [
    "CORE_DEFAULT_PROTOCOLS",
    "CORE_FORMATS",
    "CORE_FORMAT_LABELS",
    "CROSSING_PROTOCOLS",
    "DEFAULT_PORT",
    "FRAMEWORK_VERSION",
    "RULES",
    "RULE_COLUMNS",
    "STUDY_FORMAT_COUNT",
    "STUDY_PROTOCOL_COUNT",
    "TEXT_PROTOCOLS",
    "TWO_STAGE_FORMATS",
    "check_rule",
]
