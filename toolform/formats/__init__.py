"""Format renderers — the treatment axis of the study.

Import :func:`all_formats` or :func:`get_format` and everything registers
itself on first use.
"""

from .base import (
    DEFAULT_OPTIONS,
    FAMILIES,
    MINIMAL_OPTIONS,
    FormatMeta,
    RenderOptions,
    SchemaRenderer,
    all_formats,
    format_ids,
    formats_by_family,
    get_format,
    has_format,
    novel_formats,
    register,
    registry_table,
    select_formats,
)

__all__ = [
    "DEFAULT_OPTIONS",
    "FAMILIES",
    "MINIMAL_OPTIONS",
    "FormatMeta",
    "RenderOptions",
    "SchemaRenderer",
    "all_formats",
    "format_ids",
    "formats_by_family",
    "get_format",
    "has_format",
    "novel_formats",
    "register",
    "registry_table",
    "select_formats",
]
