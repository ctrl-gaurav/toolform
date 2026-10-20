"""Plain-English explanations of a recommendation, with the table behind every number."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..sdk.constants import CORE_DEFAULT_PROTOCOLS, CORE_FORMAT_LABELS
from .situation import ModelResolution

if TYPE_CHECKING:  # pragma: no cover
    from .recommend import Recommendation

_RULE_WORDS = {"main": "the main rule", "symmetric": "the symmetric rule", "as_written": "the as-written rule"}


def format_pct(x: float | None, digits: int = 2) -> str:
    """``77.7`` as ``"77.70%"``; ``"n/a"`` for None."""
    if x is None:
        return "n/a"
    return f"{x:.{digits}f}%"


def label_of(format_id: str, name: str = "") -> str:
    """The table label of a core format, else the format's name."""
    return CORE_FORMAT_LABELS.get(format_id, name or format_id)


def describe_basis(resolution: ModelResolution, basis: str) -> str:
    """Where the base number came from, in words."""
    if basis.startswith("checkpoint:"):
        return f"the checkpoint {basis[len('checkpoint:') :]}, measured on its own"
    if basis.startswith("anchor:"):
        return f"the anchor model {basis[len('anchor:') :]}, measured directly"
    if basis.startswith("family:"):
        label = resolution.family_label or basis[len("family:") :]
        return f"the {label} family"
    if resolution.matched_by == "none":
        return "the pooled tables, since the model matched nothing in the study"
    who = resolution.family or resolution.query or "this model"
    return f"the pooled tables, since the study has no family row for {who} under this rule"


def _table(x: float | None) -> str:
    """A table value at the precision the table printed it."""
    if x is None:
        return "n/a"
    text = f"{x:.2f}"
    return f"{text[:-1] if text.endswith('0') else text}%"


def explain(rec: "Recommendation") -> str:
    """Three to eight sentences on why this format and protocol, every number with its table."""
    s = rec.situation
    label = label_of(rec.format_id, rec.format_name)
    rule_words = _RULE_WORDS.get(rec.rule, rec.rule)
    parts: list[str] = []
    base = rec._base  # noqa: SLF001 - the explanation reads the recommendation's own working
    if rec.basis.startswith("family:"):
        fam = rec.resolution.family_label or rec.basis.split(":", 1)[1]
        best = rec._family_best == rec.format_id  # noqa: SLF001
        tail = ", the highest of the eight core formats" if best else ""
        note = f" ({rec._basis_note})" if rec._basis_note else ""  # noqa: SLF001
        parts.append(
            f"For the {fam} family{note} at 8 tools and tier 3, {label} scored {_table(base)} under "
            f"{rule_words}{tail} (tab_models_main)."
        )
    elif rec.basis.startswith("checkpoint:"):
        name = rec.basis.split(":", 1)[1]
        parts.append(
            f"{name} was measured on its own at 8 tools and tier 3: {label} scored {_table(base)} under "
            f"{rule_words} (tab_models_full, three seeds of 50 requests per format)."
        )
    elif rec.basis.startswith("anchor:"):
        name = rec.basis.split(":", 1)[1]
        parts.append(
            f"{name} was measured directly at 8 tools and tier 3: {label} scored {_table(base)} under "
            f"{rule_words} (tab_models_main, one model on 25 requests per format per seed)."
        )
    else:
        why = (
            "the model matched nothing in the study"
            if rec.resolution.matched_by == "none"
            else "the family evidence exists only under the main rule"
            if rec.rule != "main"
            else "the study has no row for this family"
        )
        if rec.format_id in CORE_FORMAT_LABELS:
            parts.append(
                f"Pooled over 51 checkpoints at 8 tools and tier 3, {label} scored {_table(base)} under "
                f"{rule_words} (tab_main); the pooled table is used because {why}."
            )
        else:
            parts.append(
                f"{label} scored {_table(base)} in the site export of every cell it ran in; it is "
                f"outside the eight core formats, so no shift is applied."
            )
    ratio = rec._protocol_ratio  # noqa: SLF001
    default = CORE_DEFAULT_PROTOCOLS.get(rec.format_id)
    if ratio is not None:
        sentence = (
            f"Over 35 checkpoints the answer protocol changed accuracy {ratio:.2f} times as much as the "
            f"format under {rule_words} (tab_protocol)"
        )
        cells = rec._protocol_cells  # noqa: SLF001
        if default and rec.protocol_id != default and cells:
            sentence += (
                f", and {label} scored {_table(cells[0])} with {rec.protocol_id} against "
                f"{_table(cells[1])} with {default}"
            )
        parts.append(sentence + ".")
    shifts = []
    count = rec._count_cells  # noqa: SLF001
    if count and s.n_tools != 8:
        shifts.append(
            f"the count table has {label} at {count[0]:.2f}% for {s.n_tools} tools against "
            f"{count[1]:.2f}% at 8 (tab_count_by_format)"
        )
    tier = min(s.tier, 5)
    tcells = rec._tier_cells  # noqa: SLF001
    if tcells and tier != 3:
        dropped = " (a gain measured at 8 tools, so not applied here)" if rec._tier_dropped else ""  # noqa: SLF001
        shifts.append(
            f"the tier table has it at {_table(tcells[0])} for tier {tier} against {_table(tcells[1])} at "
            f"tier 3{dropped} (tab_tier_by_format)"
        )
    if shifts:
        parts.append("Moving that to this situation in log-odds: " + "; ".join(shifts) + ".")
    parts.append(
        f"With {rec.protocol_id}, at {s.n_tools} tools and tier {tier}, the expected accuracy is "
        f"{format_pct(rec.expected_accuracy)} (range {rec.interval[0]:.2f} to {rec.interval[1]:.2f} across "
        f"the table values it rests on). The study measured each factor alone; this combination was not "
        f"itself evaluated."
    )
    if rec.schema_tokens is not None:
        how = (
            "estimated as characters / 4 from your tools"
            if rec.tokens_source == "rendered"
            else "scaled from the study's cost table at 8 tools"
        )
        parts.append(f"The tool block costs about {rec.schema_tokens:,} tokens ({how}).")
    if rec.tied_with:
        cheapest = rec._cheapest_tied  # noqa: SLF001
        if cheapest and cheapest != rec.format_id:
            parts.append(
                f"{', '.join(rec.tied_with)} {'is' if len(rec.tied_with) == 1 else 'are'} within the "
                f"tie margin; {cheapest} is the cheapest of them."
            )
        else:
            parts.append(
                f"{', '.join(rec.tied_with)} {'is' if len(rec.tied_with) == 1 else 'are'} within the tie margin."
            )
    parts.append(rec.catalogue.reason)
    if rec.guard is not None:
        parts.append(rec.guard.reason)
    return " ".join(p.strip() for p in parts if p and p.strip())


__all__ = ["describe_basis", "explain", "format_pct", "label_of"]
