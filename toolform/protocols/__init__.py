"""Call protocols — how the model answers, and how we read it back."""

from .base import (
    CallProtocol,
    ParseResult,
    ProtocolMeta,
    all_protocols,
    declares_no_call,
    get_protocol,
    protocol_ids,
    protocol_table,
    register_protocol,
    strip_reasoning,
)
from .grammars import CONSTRAINABLE, GRAMMAR_SCOPES, grammar_for, json_schema_for  # noqa: F401 (re-exported)
from .unified import LENIENT_ORDER, parse_both, parse_lenient

__all__ = [
    "CONSTRAINABLE",
    "CallProtocol",
    "LENIENT_ORDER",
    "ParseResult",
    "ProtocolMeta",
    "all_protocols",
    "declares_no_call",
    "get_protocol",
    "grammar_for",
    "json_schema_for",
    "parse_both",
    "parse_lenient",
    "protocol_ids",
    "protocol_table",
    "register_protocol",
    "strip_reasoning",
]
