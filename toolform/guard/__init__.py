"""The description guard: find and remove instructions hidden in tool metadata.

It is a rule-based heuristic that runs offline. The study measured how often
models follow a sentence planted in a tool description (38.48 to 54.16% of
turns in every format that shows one); it did not measure this detector. On a
held-out set of 50 descriptions written for it
(tests/framework/fixtures/guard_heldout.json) it flagged 12 of 25 injected
ones and 1 of 25 benign ones at high severity.
"""

from .clean import ACTIONS, SCOPES, clean_toolset, guard
from .rules import RULES, STRICTNESS, Rule, split_sentences
from .scan import Finding, GuardReport, scan_text, scan_tool, scan_toolset

__all__ = [
    "ACTIONS",
    "Finding",
    "GuardReport",
    "RULES",
    "Rule",
    "SCOPES",
    "STRICTNESS",
    "clean_toolset",
    "guard",
    "scan_text",
    "scan_tool",
    "scan_toolset",
    "split_sentences",
]
