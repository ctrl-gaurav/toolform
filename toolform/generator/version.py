"""The generator's version switch.

Every stored cell was drawn by generator v1 and keeps its universe fingerprint
for ever. Version 2 is opt-in per cell (``generator_version:
2``): variants that differ in a required field or the kernel's role, an
array-of-objects and a date argument on every create operation, a second error
type whose fix is not in the error message, a null pool of a hundred requests,
and an array sampler that fills arrays. Generation is single-threaded, so the
version is a context variable set for the duration of one ``generate_instances``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_VERSION: ContextVar[int] = ContextVar("toolform_generator_version", default=1)


def current_version() -> int:
    return _VERSION.get()


@contextmanager
def use_version(v: int):
    if v not in (1, 2):
        raise ValueError(f"generator_version must be 1 or 2, not {v!r}")
    tok = _VERSION.set(v)
    try:
        yield
    finally:
        _VERSION.reset(tok)


# v2's two extra arguments on every create operation (v1 has no array of objects
# and no date anywhere in v1). Values are drawn from these pools.
LINE_ITEM_LABELS = ("starter", "refill", "spare", "sample", "premium", "basic")
DATE_POOL = ("2027-03-04", "2027-04-19", "2027-06-01", "2027-08-23", "2027-10-12", "2027-12-05")
