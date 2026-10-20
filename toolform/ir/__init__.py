"""Canonical tool IR — the single source of truth every format renders from."""

from .canonical import (
    calls_equal,
    canonical_json,
    normalize_arguments,
    normalize_call,
    normalize_value,
)
from .types import (
    SCALAR_KINDS,
    Constraints,
    ParamIR,
    ToolCall,
    ToolIR,
    ToolUniverse,
    TypeIR,
    TypeKind,
)
from .validate import (
    ValidationReport,
    hallucinated_tool,
    validate_call,
    validate_calls,
)

__all__ = [
    "SCALAR_KINDS",
    "Constraints",
    "ParamIR",
    "ToolCall",
    "ToolIR",
    "ToolUniverse",
    "TypeIR",
    "TypeKind",
    "ValidationReport",
    "calls_equal",
    "canonical_json",
    "hallucinated_tool",
    "normalize_arguments",
    "normalize_call",
    "normalize_value",
    "validate_call",
    "validate_calls",
]
