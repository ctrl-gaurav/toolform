"""Token counts.

The framework estimates tokens as characters divided by four, the same rule
the study used for its renderer features and
the backends' fallback count. Every number it prints says whether it is such
an estimate or comes from the study's tables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


def estimate_tokens(text: str) -> int:
    """``max(1, round(len(text) / 4))``: the study's tokenizer-free estimate."""
    return max(1, round(len(text or "") / 4))


@lru_cache(maxsize=8)
def _tokenizer(name: str) -> Any:
    from transformers import AutoTokenizer  # type: ignore

    return AutoTokenizer.from_pretrained(name)


def count_tokens(text: str, tokenizer: str | None = None) -> int:
    """Count tokens with a Hugging Face tokenizer when one is named, else estimate.

    With ``tokenizer`` set and ``transformers`` installed, the text is encoded
    without special tokens. That may download the tokenizer; nothing is
    downloaded when no name is passed. Any failure falls back to
    :func:`estimate_tokens`.
    """
    if not tokenizer:
        return estimate_tokens(text)
    try:
        tok = _tokenizer(tokenizer)
        return len(tok.encode(text, add_special_tokens=False))
    except Exception:  # noqa: BLE001 - no transformers, no network, unknown name
        return estimate_tokens(text)


def describe_tokens(n: int | None, source: str = "estimate") -> str:
    """Plain words for a token number: "about 2,836 tokens, estimated as characters / 4"."""
    if n is None:
        return "an unknown number of tokens"
    if source == "study":
        return f"about {n:,} tokens, from the study's cost table"
    if source == "tokenizer":
        return f"{n:,} tokens"
    return f"about {n:,} tokens, estimated as characters / 4"


__all__ = ["count_tokens", "describe_tokens", "estimate_tokens"]
