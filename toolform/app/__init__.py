"""The product command line, ``toolform``.

``toolform recommend``, ``render``, ``parse``, ``guard``, ``catalogue``,
``convert``, ``call``, ``ab-test``, ``evidence``, ``serve``, ``doctor`` and
``version`` are its commands.
"""

from __future__ import annotations

from .cli import app, main

__all__ = ["app", "main"]
