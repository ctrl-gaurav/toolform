"""The guard's rules: heuristics for instructions hidden in tool metadata.

The study measured how often models follow one plain sentence planted in a
tool description: on 38.48 to 54.16% of turns in every format that shows the
description (tab_pressure). It did not measure this detector. The rules are
heuristics, each written to catch a shape of that sentence, and each is
checked against the study's own injected sentences and against the 66 real
tool schemas, which must raise no high finding at ``standard`` strictness.

Rules apply per sentence. A sentence ends at ``.``, ``!``, ``?`` or ``;``
followed by a space or the end of the text, or at a line break, so that a
version number or a sentinel such as ``OVERRIDE-7731`` stays whole. Every
pattern bridges at most :data:`GAP` characters, so a scan takes time linear
in the length of the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEVERITIES: tuple[str, ...] = ("high", "medium", "low")

STRICTNESS: dict[str, tuple[str, ...]] = {
    "lenient": ("high",),
    "standard": ("high", "medium"),
    "strict": ("high", "medium", "low"),
}

#: Tool descriptions longer than this, and parameter descriptions longer than
#: ``PARAM_DESC_LIMIT``, raise TS108. Heuristic thresholds, not study numbers.
TOOL_DESC_LIMIT = 1500
PARAM_DESC_LIMIT = 500


@dataclass(frozen=True)
class Rule:
    """One guard rule."""

    id: str
    name: str
    severity: str
    summary: str
    patterns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """A JSON-serialisable dict of every field."""
        return {
            "id": self.id,
            "name": self.name,
            "severity": self.severity,
            "summary": self.summary,
            "patterns": list(self.patterns),
        }


ACT_VERBS = r"(?:call|invoke|use|run|set|pass|send|include|add|respond|reply|answer|output|write|tell|say|print)"
CALL_VERBS = (
    r"(?:call|calls|calling|called|invoke|invokes|invoking|invoked|use|uses|using|run|runs|running|"
    r"execute|executes|executing|trigger|triggers|triggering)"
)
ORDER_WORDS = r"\b(?:first|before|also|then|instead)\b"

#: The longest gap a pattern bridges between its two halves. Unbounded lazy gaps rescan the rest
#: of the sentence from every trigger, which made one long description take seconds; 120
#: characters is longer than any instruction in the study's injected sentences.
GAP = 120

#: An imperative that asks for something. "ignore" and "disregard" are not here: on their own they
#: are ordinary ("Ignore case when matching"); TS101_OVERRIDE covers them with an object.
TS101_POSITIVE = (
    r"\b(?:always|you must|you should|make sure|be sure to|instead|"
    r"before (?:calling|using)|when (?:calling|using) this tool)\b"
)
#: A restriction. Tool documentation is full of these ("Do not use this tool for math"), so alone
#: they are a low finding.
TS101_NEGATIVE = r"\b(?:do not|don't|never)\b"
TS101_TRIGGER = TS101_POSITIVE[:-3] + r"|do not|don't|never)\b"
TS101 = TS101_TRIGGER + r".{0," + str(GAP) + r"}?\b" + ACT_VERBS + r"\b"
TS101_POSITIVE_ACT = TS101_POSITIVE + r".{0," + str(GAP) + r"}?\b" + ACT_VERBS + r"\b"
TS101_NEGATIVE_ACT = TS101_NEGATIVE + r".{0," + str(GAP) + r"}?\b" + ACT_VERBS + r"\b"
#: Text addressed to the model, or about the conversation rather than the tool.
TS101_ADDRESSED = (
    r"\bnote to the (?:assistant|model|ai|llm)\b|"
    r"\bthe (?:assistant|model|ai|llm) (?:should|must|will|needs to|has to)\b|"
    r"\b(?:regardless of|whatever) (?:what )?the user\b|"
    r"\bbefore (?:answering|responding|replying|handling)\b|\binstead of (?:answering|responding)\b|"
    r"\bwhen the user asks\b.{0," + str(GAP) + r"}?\b(?:reply|respond|say|answer|tell)\b|"
    r"\bin your (?:reply|response|answer|final answer)\b"
)
#: An instruction to drop other instructions.
TS101_OVERRIDE = (
    r"\b(?:ignore|disregard|forget)\s+(?:(?:all|any|the|your|every)\s+)?(?:previous|prior|above|"
    r"earlier|other|preceding|system|original)\b|"
    r"\b(?:ignore|disregard|forget)\s+(?:(?:all|any|every|your|these|those)\s+)?"
    r"(?:instructions?|rules?|guidelines?)\b|"
    r"\b(?:ignore|disregard)\s+(?:the\s+)?(?:user's|user)\s+(?:question|request|message|"
    r"instructions?)\b|\b(?:ignore|disregard)\s+the\s+request\b"
)
#: An instruction to change every answer.
TS101_TAMPER = (
    r"\b(?:append|add|include|insert|prepend|attach)\b.{0,80}?\b(?:to|in|into)\s+"
    r"(?:every|each|all|your|the final)\s+(?:final\s+)?(?:answer|reply|response|message|output)s?\b"
)
#: Verbs that direct what the model says to the user.
OUTPUT_VERBS = r"\b(?:respond|reply|answer|say|tell|output|print)\b"
SENSITIVE_WORDS = r"\b(?:secret|secrets|password|passwords|credential|credentials|private key)\b"

#: ``set the notify parameter to X``, ``pass `limit` as 7``, ``use mode=fast``.
TS102 = (
    r"\b(?:set|pass|use|fill|put)\s+(?:the\s+)?[`'\"]?(?P<ident>[A-Za-z_][A-Za-z0-9_.\-]*)[`'\"]?"
    r"(?:\s+(?:parameter|argument|field|value))?\s*(?:\bto\b|\bas\b|=|\bwith\b)\s*"
    r"(?P<value>'[^']*'|\"[^\"]*\"|`[^`]*`|[^\s,;]+)"
)
SENTINEL = r"^(?=[A-Z0-9_\-]*\d)[A-Z0-9_\-]{4,}$"

TS105_PHRASES = (
    r"\b(?:do not|don't|never) (?:tell|mention|inform|reveal|show)\b|"
    r"\bwithout (?:asking|telling|confirming)\b|\bsecretly\b|"
    r"\bkeep (?:this|it) (?:secret|hidden|confidential)\b"
)
TS105_SILENT = r"\bsilently\b.{0," + str(GAP) + r"}?\b" + ACT_VERBS + r"\b"
#: Bounded, and anchored at the start of a word, so a long run of letters with no "@" is read once.
URL_OR_EMAIL = (
    r"(?:https?://[^\s'\"<>]+|(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}"
    r"(?:\.[A-Za-z0-9\-]{1,63}){0,8}\.[A-Za-z]{2,24}(?![A-Za-z]))"
)
#: A verb of sending, including a tool name built on one (``send_email``), then an address.
TS105_EXFIL = (
    r"\b(?:send|post|upload|forward|report|e-?mail|mail|share|copy|transmit|exfiltrate)[A-Za-z_]*\b"
    r"[^.;!?\n]{0,200}?\b(?:to|at)\s+" + URL_OR_EMAIL
)
#: Reading or sending a file that holds keys. The verb is required: a real shell tool says that
#: reads of ~/.ssh are refused, which is documentation.
TS105_PATHS = (
    r"\b(?:read|cat|open|include|send|upload|print|copy|attach|return|output|show|leak)\b"
    r".{0," + str(GAP) + r"}?(?:~/\.ssh\b|\bid_(?:rsa|dsa|ecdsa|ed25519)\b|/etc/(?:passwd|shadow)\b|"
    r"\.aws/credentials\b|(?<![A-Za-z0-9_])\.env\b|\.netrc\b)"
)

TS106_MARKUP = (
    r"<\|im_start\|>|<\|im_end\|>|<\|eot_id\|>|\[INST\]|<<SYS>>|<system>|</tool>|</tools>|"
    r"<tool_call>|(?im:^\s*(?:system|assistant)\s*:)|(?im:^\s*###\s*instruction)"
)
TS107_CAPS = r"\b(?:IMPORTANT|CRITICAL|MANDATORY)\b|\bREQUIRED:"
TS107_PHRASES = (
    r"(?i:\bthis overrides\b|\boverrides? (?:all|any|every|other|previous)\b|\bhighest priority\b|"
    r"\bfrom the system\b|\bdeveloper note\b|\bsystem (?:instruction|prompt|message)\b|"
    r"\btakes? precedence\b)"
)
TS109_CHARS = r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
TS109_COMMENT = r"<!--.*?-->"


def html_comments(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of every HTML comment, found in one pass (a regex rescans from every opener)."""
    out: list[tuple[int, int]] = []
    i = 0
    while True:
        a = text.find("<!--", i)
        if a < 0:
            return out
        b = text.find("-->", a + 4)
        if b < 0:
            return out
        out.append((a, b + 3))
        i = b + 3


#: Cyrillic and Greek letters that look like Latin ones, folded before any pattern runs, so the
#: study's hijack sentence written with a Cyrillic "а" is read as the Latin one. One character
#: maps to one, so every offset stays the same.
CONFUSABLES: dict[str, str] = {
    "а": "a",
    "в": "b",
    "е": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "ԛ": "q",
    "ԝ": "w",
    "һ": "h",
    "ӏ": "l",
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "Ԁ": "D",
    "Ԛ": "Q",
    "Ԝ": "W",
    "α": "a",
    "ε": "e",
    "ι": "i",
    "κ": "k",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
    "υ": "u",
    "χ": "x",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
}
_FOLD = str.maketrans(CONFUSABLES)
#: A word that mixes Latin letters with Cyrillic or Greek ones.
TS110_MIXED = (
    r"(?=[A-Za-z\u0370-\u03ff\u0400-\u04ff\u0500-\u052f]*[A-Za-z])"
    r"(?=[A-Za-z\u0370-\u03ff\u0400-\u04ff\u0500-\u052f]*[\u0370-\u03ff\u0400-\u04ff\u0500-\u052f])"
    r"[A-Za-z\u0370-\u03ff\u0400-\u04ff\u0500-\u052f]+"
)


def fold_confusables(text: str) -> str:
    """``text`` with Cyrillic and Greek lookalikes replaced by the Latin letter; same length."""
    return text.translate(_FOLD)


RULES: tuple[Rule, ...] = (
    Rule(
        "TS101",
        "hidden_instruction",
        "high",
        "An instruction addressed to the model. High when it has a target: a literal value, a tool to "
        "call, what to say, a secret, or words aimed at the model or at its other instructions. Medium "
        'for any other imperative, low for a restriction such as "do not use this tool for math".',
        (TS101, TS101_ADDRESSED, TS101_OVERRIDE, TS101_TAMPER),
    ),
    Rule(
        "TS102",
        "sentinel_value",
        "high",
        "A sentence that assigns a literal value to an argument, such as a parameter name or a code "
        "like OVERRIDE-7731.",
        (TS102,),
    ),
    Rule(
        "TS103",
        "calls_other_tool",
        "high",
        "The text names a tool of the catalogue next to a verb of calling. High when it also says "
        'first, before, also, then or instead, unless it states a prerequisite of this tool ("call '
        'list_files before read_file" on read_file); medium otherwise.',
        (CALL_VERBS, ORDER_WORDS),
    ),
    Rule(
        "TS104",
        "schema_mismatch",
        "medium",
        "The text names an identifier that is not a parameter of this tool, nor a tool's name.",
        (),
    ),
    Rule(
        "TS105",
        "secrecy_or_exfiltration",
        "high",
        "The text asks for secrecy, to send something to an address, or names a file that holds keys.",
        (TS105_PHRASES, TS105_SILENT, TS105_EXFIL, TS105_PATHS),
    ),
    Rule("TS106", "role_markup", "high", "Chat-template or role markup inside tool metadata.", (TS106_MARKUP,)),
    Rule(
        "TS107",
        "urgency_or_authority",
        "medium",
        "Words that claim authority (this overrides, from the system, takes precedence): medium. "
        "IMPORTANT, CRITICAL or MANDATORY: medium beside an instruction, low alone.",
        (TS107_CAPS, TS107_PHRASES),
    ),
    Rule(
        "TS108",
        "oversized_description",
        "low",
        f"A tool description over {TOOL_DESC_LIMIT:,} characters or a parameter description over "
        f"{PARAM_DESC_LIMIT} characters: room to hide text.",
        (),
    ),
    Rule(
        "TS109",
        "non_printing_text",
        "high",
        "Zero-width or bidirectional control characters, or an HTML comment: text a reader does not see.",
        (TS109_CHARS, TS109_COMMENT),
    ),
    Rule(
        "TS110",
        "lookalike_letters",
        "medium",
        "A word that mixes Latin letters with Cyrillic or Greek ones, which can hide an instruction "
        "from a pattern. The other rules read such text with the lookalikes folded to Latin.",
        (TS110_MIXED,),
    ),
)

RULES_BY_ID: dict[str, Rule] = {r.id: r for r in RULES}

#: A sentence ends at a terminator followed by a space, the end, or an invisible character (a
#: zero-width space after the full stop must not glue two sentences together).
_AFTER = r"(?=\s|$|[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff])"
_BOUNDARY = re.compile(r"[.!?;]+" + _AFTER + r"|\n")
_BOUNDARY_NO_SEMICOLON = re.compile(r"[.!?]+" + _AFTER + r"|\n")


def split_sentences(text: str, *, semicolons: bool = True) -> list[tuple[int, int, str]]:
    """Split text into sentences; returns ``(start, end, sentence)`` spans, whitespace trimmed.

    Detection splits at ``;`` too, so one clause is judged alone. Removal uses
    ``semicolons=False``, so stripping takes the whole sentence and never
    leaves half of one behind.
    """
    spans: list[tuple[int, int, str]] = []
    start = 0
    for m in (_BOUNDARY if semicolons else _BOUNDARY_NO_SEMICOLON).finditer(text):
        end = m.end() if m.group(0) != "\n" else m.start()
        _add(text, start, end, spans)
        start = m.end()
    _add(text, start, len(text), spans)
    return spans


def _add(text: str, start: int, end: int, spans: list[tuple[int, int, str]]) -> None:
    chunk = text[start:end]
    if not chunk.strip():
        return
    lead = len(chunk) - len(chunk.lstrip())
    trail = len(chunk) - len(chunk.rstrip())
    s, e = start + lead, end - trail
    spans.append((s, e, text[s:e]))


__all__ = [
    "ACT_VERBS",
    "CALL_VERBS",
    "CONFUSABLES",
    "GAP",
    "PARAM_DESC_LIMIT",
    "RULES",
    "RULES_BY_ID",
    "Rule",
    "SEVERITIES",
    "STRICTNESS",
    "TOOL_DESC_LIMIT",
    "fold_confusables",
    "html_comments",
    "split_sentences",
]
