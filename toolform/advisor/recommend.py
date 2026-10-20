"""Recommend a schema format and an answer protocol from the study's evidence.

The algorithm is deterministic and small enough to port (the website runs the
same rule in TypeScript). In short: take the base accuracy of each candidate
format for the model (its own checkpoint row, its anchor row, its family
row, or the pooled table), move it by the shifts the pooled tables measured
for the tool count, the tier and the protocol, rank, and attach the catalogue
and guard advice.

The study measured each factor alone, at 8 tools and tier 3; no table crossed
two of them, and this combination was not itself evaluated. Two choices keep
it inside what was measured:

* Shifts combine in log-odds, not in points, so an estimate can never pass 0
  or 100 and a strong base is not pushed past what any table saw.
* A tier gain was measured at 8 tools only. At any other tool count it is not
  applied (a tier loss is), so an easy tier cannot lift a 256-tool estimate
  above the count table. A warning says so.

The range beside the point is the lowest and highest of the table cells and
single-factor estimates it rests on. It is not a confidence interval.

Measuring eight formats on the target model did better than every rule in the
study (69.18% against 64.35% for the fitted rule), so every recommendation
says how to do that.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from ..formats import get_format
from ..protocols import get_protocol
from ..sdk.constants import (
    CORE_DEFAULT_PROTOCOLS,
    CORE_FORMAT_LABELS,
    CORE_FORMATS,
    CROSSING_PROTOCOLS,
    TEXT_PROTOCOLS,
    TWO_STAGE_FORMATS,
)
from ..sdk.cost import PRICES, cost_of
from .evidence import Evidence, EvidenceRow, load_evidence
from .explain import explain, format_pct, label_of
from .situation import ModelResolution, Situation, resolve_model

if TYPE_CHECKING:  # pragma: no cover
    from ..sdk.toolset import Toolset

log = logging.getLogger("toolform.advisor")

#: A protocol switch needs at least this gain, the tie threshold of
#: ``toolform.laws.SelectionRule`` (0.02 in proportion) in percent.
SWITCH_GAIN = 2.0
#: Candidates within this many points of the winner's expected accuracy are tied.
TIE_POINTS = 2.0
#: Under the cost objective, candidates within this share of the winner's score are tied.
TIE_SHARE = 0.02
#: Tool counts the study measured (tab_count_by_format); others are interpolated in log2.
MEASURED_COUNTS = (1, 2, 4, 8, 16, 32, 64, 128, 256)
TWO_STAGE_FROM = 64
RETRIEVE_FROM = 32
CONTEXT_SHARE = 0.5
MAX_MEASURED_TIER = 5
#: Families whose chat template thinks by default; the study turned thinking off for them.
THINKING_FAMILIES: tuple[str, ...] = ("qwen3", "qwen3.5", "qwen3.5-large")


def logit(p: float) -> float:
    """Log-odds of a percentage, kept finite by bounding it to 0.5 to 99.5."""
    q = min(max(float(p), 0.5), 99.5) / 100.0
    return math.log(q / (1.0 - q))


def expit(x: float) -> float:
    """A log-odds back to a percentage."""
    return 100.0 / (1.0 + math.exp(-x))


def table_pct(x: float | None) -> str:
    """A table value at the precision the table printed it: ``77.7%``, ``67.52%``."""
    if x is None:
        return "n/a"
    text = f"{x:.2f}"
    return f"{text[:-1] if text.endswith('0') else text}%"


@dataclass
class Alternative:
    """Another candidate, with its expected accuracy and cost."""

    format_id: str
    format_name: str
    protocol_id: str
    expected_accuracy: float
    schema_tokens: int | None
    cost_per_request: float | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "format_id": self.format_id,
            "format_name": self.format_name,
            "protocol_id": self.protocol_id,
            "expected_accuracy": round(self.expected_accuracy, 2),
            "schema_tokens": self.schema_tokens,
            "cost_per_request": None if self.cost_per_request is None else round(self.cost_per_request, 8),
            "score": round(self.score, 6),
        }


@dataclass
class CatalogueAdvice:
    """How to show a catalogue of this size: all at once, retrieved, or names first."""

    strategy: str
    reason: str
    evidence: list[EvidenceRow]

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {"strategy": self.strategy, "reason": self.reason, "evidence": [e.to_dict() for e in self.evidence]}


@dataclass
class GuardAdvice:
    """What to do about third-party tool descriptions."""

    action: str
    reason: str
    evidence: list[EvidenceRow]

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {"action": self.action, "reason": self.reason, "evidence": [e.to_dict() for e in self.evidence]}


@dataclass
class Recommendation:
    """A format and protocol for one situation, with the evidence behind them."""

    format_id: str
    format_name: str
    protocol_id: str
    protocol_name: str
    expected_accuracy: float
    interval: tuple[float, float]
    interval_kind: str
    basis: str
    rule: str
    objective: str
    schema_tokens: int | None
    tokens_source: str
    cost_per_request: float | None
    tied_with: list[str]
    alternatives: list[Alternative]
    catalogue: CatalogueAdvice
    guard: GuardAdvice | None
    measure_hint: str
    surface: dict[str, Any] | None
    evidence: list[EvidenceRow]
    explanation: str
    warnings: list[str]
    resolution: ModelResolution
    situation: Situation
    evidence_version: str
    context_tokens: int | None = None
    _base: float = field(default=0.0, repr=False, compare=False)
    _count_cells: tuple[float, float] | None = field(default=None, repr=False, compare=False)
    _tier_cells: tuple[float, float] | None = field(default=None, repr=False, compare=False)
    _tier_dropped: bool = field(default=False, repr=False, compare=False)
    _protocol_cells: tuple[float, float] | None = field(default=None, repr=False, compare=False)
    _protocol_ratio: float | None = field(default=None, repr=False, compare=False)
    _family_best: str | None = field(default=None, repr=False, compare=False)
    _cheapest_tied: str | None = field(default=None, repr=False, compare=False)
    _basis_note: str = field(default="", repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of the public fields."""
        return {
            "format_id": self.format_id,
            "format_name": self.format_name,
            "protocol_id": self.protocol_id,
            "protocol_name": self.protocol_name,
            "expected_accuracy": round(self.expected_accuracy, 2),
            "interval": [round(self.interval[0], 2), round(self.interval[1], 2)],
            "interval_kind": self.interval_kind,
            "basis": self.basis,
            "rule": self.rule,
            "objective": self.objective,
            "schema_tokens": self.schema_tokens,
            "tokens_source": self.tokens_source,
            "cost_per_request": None if self.cost_per_request is None else round(self.cost_per_request, 8),
            "tied_with": list(self.tied_with),
            "alternatives": [a.to_dict() for a in self.alternatives],
            "catalogue": self.catalogue.to_dict(),
            "guard": self.guard.to_dict() if self.guard else None,
            "measure_hint": self.measure_hint,
            "surface": self.surface,
            "evidence": [e.to_dict() for e in self.evidence],
            "explanation": self.explanation,
            "warnings": list(self.warnings),
            "resolution": self.resolution.to_dict(),
            "situation": self.situation.to_dict(),
            "evidence_version": self.evidence_version,
            "context_tokens": self.context_tokens,
            "basis_note": self._basis_note,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        """One line: format + protocol, expected accuracy with its range, and the basis."""
        if self.basis.startswith("family:"):
            basis = f"family {self.basis.split(':', 1)[1]}"
            if self._basis_note:
                basis += f" ({self._basis_note})"
        elif self.basis.startswith("anchor:"):
            basis = f"anchor {self.basis.split(':', 1)[1]}"
        elif self.basis.startswith("checkpoint:"):
            basis = f"checkpoint {self.basis.split(':', 1)[1]}"
        else:
            basis = "pooled evidence"
        return (
            f"{self.format_id} + {self.protocol_id}, {self.expected_accuracy:.2f}% expected "
            f"({self.interval[0]:.2f} to {self.interval[1]:.2f} across the table values), {basis}"
        )


@dataclass
class _Scored:
    format_id: str
    protocol_id: str
    base: float
    expected: float
    interval: tuple[float, float]
    schema_tokens: int | None
    tokens_source: str
    cost: float | None
    rows: list[EvidenceRow]
    core: bool
    score: float = 0.0
    count_cells: tuple[float, float] | None = None
    tier_cells: tuple[float, float] | None = None
    tier_dropped: bool = False
    protocol_cells: tuple[float, float] | None = None
    penalty: list[str] = field(default_factory=list)
    kept_default: tuple[str, float] | None = None


def _nearest_count(counts: list[int], n: int) -> int:
    """The measured count nearest ``n`` in log2; a tie goes to the larger count."""
    return min(counts, key=lambda c: (abs(math.log2(max(1, n)) - math.log2(c)), -c))


def _signed_pct(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}{abs(v):.2f}%"


def _disclosure_sentence(nd: dict[str, Any]) -> str:
    """What names-and-descriptions-first did against one shot at the nearest measured count, in words."""
    v = nd["minus_json"]["value"]
    iv = nd["minus_json"]["interval"]
    zero = bool(iv and iv[0] <= 0 <= iv[1])
    if zero:
        verb = f"changed accuracy by {_signed_pct(v)} against one shot, with an interval that includes zero"
    elif v > 0:
        verb = f"gained {v:.2f}% over one shot"
    else:
        verb = f"lost {abs(v):.2f}% against one shot"
    return f"at {nd['n_tools']} tools, showing names and descriptions first {verb} (tab_disclosure_v2)"


def catalogue_advice(
    n_tools: int,
    schema_tokens: int | None,
    context_tokens: int | None,
    evidence: Evidence | None = None,
    *,
    force_two_stage: bool = False,
    budget_tokens: int | None = None,
) -> CatalogueAdvice:
    """One shot, retrieval or names-first disclosure, from the study's thresholds.

    Two-stage from 64 tools, or when the tool block would take more than half
    the context window or more than ``budget_tokens``; retrieval from 32 to
    63 tools; one shot below. The catalogue module's planner uses this same
    function, so the two agree.
    """
    ev = evidence or load_evidence()
    over_context = bool(context_tokens and schema_tokens is not None and schema_tokens > CONTEXT_SHARE * context_tokens)
    over_budget = bool(budget_tokens and schema_tokens is not None and schema_tokens > budget_tokens)
    overall = ev.load("tool_count")["data"]["overall"]
    counts = [r["n_tools"] for r in overall]
    near = _nearest_count(counts, n_tools)
    empty_row = next(r for r in overall if r["n_tools"] == near)
    dis = {r["arm"]: r for r in ev.disclosure_rows(n_tools)}
    nd = dis.get("names_desc")
    rows: list[EvidenceRow] = []
    if nd is not None:
        iv = nd["minus_json"]["interval"]
        rows.append(
            EvidenceRow(
                source="paper:tab_disclosure_v2",
                label=f"names and descriptions first, minus one shot, at {nd['n_tools']} tools",
                value=nd["minus_json"]["value"],
                interval=tuple(iv) if iv else None,
                note="53 checkpoints, three seeds",
            )
        )
    if force_two_stage or n_tools >= TWO_STAGE_FROM or over_context or over_budget:
        size = f"about {schema_tokens:,} tokens" if schema_tokens is not None else "the tool block"
        if force_two_stage and not (n_tools >= TWO_STAGE_FROM or over_context or over_budget):
            why = "no core format fits the token budget"
        elif over_budget and n_tools < TWO_STAGE_FROM:
            why = f"the tool block ({size}) is over the token budget of {budget_tokens:,}"
        elif over_context and n_tools < TWO_STAGE_FROM:
            why = f"the tool block ({size}) would take more than half of the {context_tokens:,}-token context window"
        else:
            why = f"{n_tools} tools is past the point where the one-shot block starts to fill the window"
        parts = [f"Show the names first, then one schema, because {why}."]
        if nd is not None:
            text = _disclosure_sentence(nd)
            parts.append(text[0].upper() + text[1:] + ".")
        if empty_row["empty"] > 0:
            rows.append(
                EvidenceRow(
                    source="paper:tab_count",
                    label=f"turns with no answer at {near} tools",
                    value=empty_row["empty"],
                    note="pooled over the eight core formats",
                )
            )
            parts.append(f"At {near} tools, {empty_row['empty']:.2f}% of one-shot turns returned nothing (tab_count).")
        return CatalogueAdvice(strategy="two_stage", reason=" ".join(parts), evidence=rows)
    if n_tools >= RETRIEVE_FROM:
        retr = {r["label"]: r["accuracy"] for r in ev.load("tool_count")["data"]["retrieval"]}
        whole, top8 = retr.get("128 shown whole"), retr.get("top 8, BM25")
        rows = [
            EvidenceRow(
                source="paper:tab_count", label="128-tool panel shown whole", value=whole, note="55 checkpoints"
            ),
            EvidenceRow(
                source="paper:tab_count",
                label="top 8 of the 128-tool panel by BM25",
                value=top8,
                note="55 checkpoints; the gold tool is not forced in",
            ),
        ] + rows
        reason = (
            f"Retrieve the tools that match each request before showing them: on a 128-tool panel the top 8 "
            f"by BM25 reached {format_pct(top8)} against {format_pct(whole)} for the whole panel (tab_count). "
            f"Retrieval needs the request text, so it runs per request."
        )
        return CatalogueAdvice(strategy="retrieve", reason=reason, evidence=rows)
    if nd is not None:
        reason = (
            f"Show every tool at once; below {RETRIEVE_FROM} tools the block fits the window. For reference, "
            f"{_disclosure_sentence(nd)}, at the price of a second model call per request."
        )
    else:  # pragma: no cover - the evidence always has rows
        reason = "Show every tool at once."
    return CatalogueAdvice(strategy="one_shot", reason=reason, evidence=rows)


def _guard_advice(format_id: str, ev: Evidence) -> GuardAdvice:
    f = {x["id"]: x for x in ev.facts()}
    rows: list[EvidenceRow] = []
    inj = ev.injection_row(format_id)
    if inj is not None:
        rows.append(
            EvidenceRow(
                source="paper:tab_pressure",
                label=f"hidden instruction followed, {label_of(format_id)}",
                value=inj["hijack"],
                note="51 checkpoints",
            )
        )
    else:
        rows.append(
            EvidenceRow(
                source="paper:tab_pressure",
                label="hidden instruction followed, formats that show a description",
                value=None,
                note=f"{f['injection_min']['value']} to {f['injection_max']['value']}%",
            )
        )
    for fid, label in (
        ("trust_line_sentinel", "effect of a trust sentence, sentinel payload"),
        ("trust_line_valid", "effect of a trust sentence, valid payload"),
    ):
        iv = f[fid].get("interval")
        rows.append(
            EvidenceRow(
                source="paper:tab_injection_trust",
                label=label,
                value=f[fid]["value"],
                interval=tuple(iv) if iv else None,
            )
        )
    # The results section states this range as -1.94 to +1.86. Its two sources disagree with that sign:
    # the ladder appendix says removing descriptions costs 1.86% over all cells, and tab_components4 gives
    # -1.94 for adding them. Until the paper is corrected, the row quotes the two sources as they read.
    rows.append(
        EvidenceRow(
            source="paper:tab_ladder",
            label="accuracy effect of removing descriptions, all cells",
            value=None,
            note="the ladder appendix: removing them costs 1.86%; tab_components4: "
            "adding them changes accuracy by -1.94%",
        )
    )
    rows.append(
        EvidenceRow(
            source="paper:tab_ladder",
            label="Python stub without its docstring",
            value=f["descriptions_off_python_stub"]["value"],
        )
    )
    lo, hi = f["injection_min"]["value"], f["injection_max"]["value"]
    if format_id == "json_minimal":
        return GuardAdvice(
            action="none",
            reason="The minimal schema shows no description; it followed no hijack in the study (tab_pressure).",
            evidence=rows,
        )
    rate = f" ({format_pct(inj['hijack'])} for {label_of(format_id)})" if inj else ""
    reason = (
        f"Strip instructions from third-party descriptions: in every format that shows a description, models "
        f"followed one planted sentence on {lo:.2f} to {hi:.2f}% of turns{rate} (tab_pressure), and a system "
        f"sentence calling tool metadata untrusted changed that by "
        f"{f['trust_line_sentinel']['value']:+.2f}% (tab_injection_trust)."
    )
    if format_id == "python_stub":
        reason += (
            f" Do not drop descriptions with the Python stub: its docstring is its parameter documentation, "
            f"and removing it cost {abs(f['descriptions_off_python_stub']['value']):.2f}%."
        )
    return GuardAdvice(action="strip", reason=reason, evidence=rows)


def _measure_hint(ev: Evidence, thinking_off: bool = False) -> str:
    f = {x["id"]: x["value"] for x in ev.facts()}
    switch = (
        (
            " Pass --no-thinking: this family's chat template thinks by default, the study turned it off, "
            "and a reply cut off inside its thinking counts as wrong."
        )
        if thinking_off
        else ""
    )
    return (
        f"If you can call the model, run toolform ab-test. In the study, measuring eight formats on the "
        f"target model reached {f['measure_eight']:.2f}%, against {f['fitted_rule']:.2f}% for the fitted "
        f"rule, {f['always_xml']:.2f}% for always XML and {f['always_json']:.2f}% for the JSON Schema default "
        f"(tab:selection).{switch}"
    )


def completion_tokens(ev: Evidence, protocol_id: str) -> float | None:
    """Mean output tokens of a protocol: the tab_cost rows of the core formats whose default it is.

    tab_cost measured each format with its own protocol, so a format paired
    with another protocol is priced with that protocol's output length. None
    when no core format answers with it.
    """
    rows = [ev.cost_row(f) for f, p in CORE_DEFAULT_PROTOCOLS.items() if p == protocol_id]
    vals = [float(r["completion"]) for r in rows if r is not None]
    return sum(vals) / len(vals) if vals else None


def open_params_range(ev: Evidence) -> tuple[float, float] | None:
    """The smallest and largest open-weight checkpoint of the study, in billions."""
    sizes = [c["params_b"] for c in ev.load("families")["data"].get("checkpoints", []) if c.get("params_b")]
    return (min(sizes), max(sizes)) if sizes else None


class Advisor:
    """Recommends a format and protocol. Holds the evidence it reads."""

    def __init__(self, evidence: Evidence | None = None) -> None:
        self.evidence = evidence or load_evidence()

    # ------------------------------------------------------------ one format
    def _base(
        self, fid: str, s: Situation, res: ModelResolution, label: str, rows: list[EvidenceRow]
    ) -> tuple[float | None, bool]:
        """The model's own row for ``fid`` under the main rule: checkpoint, anchor, then family."""
        ev = self.evidence
        if s.rule != "main":
            return None, False
        if res.checkpoint:
            row = ev.checkpoint_row(res.checkpoint)
            if row is not None and row["accuracy"].get(fid) is not None:
                v = float(row["accuracy"][fid])
                rows.append(
                    EvidenceRow(
                        source="paper:tab_models_full",
                        label=f"{row['id']}, {label}, 8 tools, tier 3, main rule",
                        value=v,
                        note="one checkpoint, three seeds of 50 requests per format",
                    )
                )
                return v, True
        if res.anchor:
            row = ev.anchor_row(res.anchor)
            if row is not None and row["accuracy"].get(fid) is not None:
                v = float(row["accuracy"][fid])
                rows.append(
                    EvidenceRow(
                        source="paper:tab_models_main",
                        label=f"{res.anchor}, {label}, 8 tools, tier 3, main rule",
                        value=v,
                        note="one model, 25 requests per format per seed",
                    )
                )
                return v, True
        if res.family:
            row = ev.family_row(res.family)
            if row is not None and row["accuracy"].get(fid) is not None:
                v = float(row["accuracy"][fid])
                n_ck = row["checkpoints"]
                rows.append(
                    EvidenceRow(
                        source="paper:tab_models_main",
                        label=f"{row['label']} family, {label}, 8 tools, tier 3, main rule",
                        value=v,
                        note=f"mean of {n_ck} checkpoint{'s' if n_ck != 1 else ''}",
                    )
                )
                return v, True
        return None, False

    def _score(
        self, fid: str, s: Situation, res: ModelResolution, tier: int, tools: "Toolset | None", warnings: list[str]
    ) -> _Scored | None:
        ev = self.evidence
        rows: list[EvidenceRow] = []
        rule = s.rule
        core = fid in CORE_FORMATS
        default = CORE_DEFAULT_PROTOCOLS.get(fid) or get_format(fid).meta.default_protocol
        if not core:
            meta = ev.format_meta(fid)
            measured = (meta.get("measured") or {}).get("call_exact")
            if measured is None:
                warnings.append(f"{fid} has no measured row in the evidence; it is left out")
                return None
            p = s.protocol or default
            if s.protocol and s.protocol != default:
                warnings.append(f"no measurement pairs {fid} with {s.protocol}")
            rows.append(
                EvidenceRow(
                    source="export:format_leaderboard",
                    label=f"{meta['name']}, pooled over its cells",
                    value=measured,
                    note="site export, not the paper's tables",
                )
            )
            tokens, source, cost = self._tokens(fid, p, s, tools, warnings)
            return _Scored(fid, p, measured, measured, (measured, measured), tokens, source, cost, rows, core=False)

        label = CORE_FORMAT_LABELS[fid]
        pooled = ev.core_accuracy(fid, rule)
        base, specific = self._base(fid, s, res, label, rows)
        if base is None:
            base = pooled
        rows.append(
            EvidenceRow(
                source="paper:tab_main",
                label=f"{label}, pooled, 8 tools, tier 3, {rule} rule",
                value=pooled,
                note="51 checkpoints, seeds 0 to 2",
            )
        )
        n = s.n_tools
        c_n, _ = ev.count_accuracy(fid, n)
        c_8, _ = ev.count_accuracy(fid, 8)
        t_t = ev.tier_accuracy(fid, tier)
        t_3 = ev.tier_accuracy(fid, 3)
        dn = logit(c_n) - logit(c_8)
        dt_raw = logit(t_t) - logit(t_3)
        # The tier table was measured at 8 tools. Its gain is not carried to other counts; its loss is.
        dt = dt_raw if (n == 8 or dt_raw < 0) else 0.0
        tier_dropped = dt_raw > 0 and dt == 0.0
        if n != 8:
            rows.append(
                EvidenceRow(
                    source="paper:tab_count_by_format",
                    label=f"{label} at {n} tools",
                    value=c_n,
                    note=f"against {c_8:.2f} at 8 tools"
                    if n in MEASURED_COUNTS
                    else f"against {c_8:.2f} at 8 tools; interpolated in log2 between measured counts",
                )
            )
        if tier != 3:
            rows.append(
                EvidenceRow(
                    source="paper:tab_tier_by_format",
                    label=f"{label} at tier {tier}",
                    value=t_t,
                    note=f"against {t_3:.2f} at tier 3, at 8 tools"
                    + ("; the gain is not applied at other tool counts" if tier_dropped else ""),
                )
            )
        # protocol
        dp = 0.0
        p = default
        kept_default: tuple[str, float] | None = None
        cross_d = ev.crossing(rule, fid, default) if default in CROSSING_PROTOCOLS else None
        if s.protocol:
            p = s.protocol
            if p != default:
                cross_p = ev.crossing(rule, fid, p) if p in CROSSING_PROTOCOLS else None
                if cross_p is not None and cross_d is not None:
                    dp = logit(cross_p) - logit(cross_d)
                else:
                    warnings.append(f"no measurement pairs {fid} with {p}")
        elif cross_d is not None:
            best_p, best_v = default, cross_d
            for q in CROSSING_PROTOCOLS:
                v = ev.crossing(rule, fid, q)
                if v is not None and v > best_v:
                    best_p, best_v = q, v
            if best_v - cross_d >= SWITCH_GAIN:
                if specific:
                    # The crossing table pools 35 checkpoints; this model's own row was measured with the
                    # format's default protocol, and a pooled switch can go the wrong way for one family.
                    kept_default = (best_p, best_v - cross_d)
                else:
                    p, dp = best_p, logit(best_v) - logit(cross_d)
        cross_p = ev.crossing(rule, fid, p) if p in CROSSING_PROTOCOLS else None
        if cross_p is not None:
            rows.append(
                EvidenceRow(
                    source="paper:tab_protocol",
                    label=f"{label} with {p}, {rule} rule",
                    value=cross_p,
                    note="35 checkpoints, 8 tools, tier 3",
                )
            )
        lb = logit(base)
        expected = expit(lb + dn + dt + dp)
        cells = [base, pooled, c_n, t_t] + ([cross_p] if cross_p is not None else [])
        views = cells + [expit(lb + dn), expit(lb + dt), expit(lb + dp), expected]
        interval = (min(views), max(views))
        tokens, source, cost = self._tokens(fid, p, s, tools, warnings)
        return _Scored(
            fid,
            p,
            base,
            expected,
            interval,
            tokens,
            source,
            cost,
            rows,
            core=True,
            count_cells=(c_n, c_8),
            tier_cells=(t_t, t_3),
            tier_dropped=tier_dropped,
            protocol_cells=(cross_p, cross_d) if (dp and cross_p is not None and cross_d is not None) else None,
            kept_default=kept_default,
        )

    def _tokens(
        self, fid: str, protocol_id: str, s: Situation, tools: "Toolset | None", warnings: list[str]
    ) -> tuple[int | None, str, float | None]:
        ev = self.evidence
        row = ev.cost_row(fid)
        if tools is not None:
            from ..sdk.rendering import render
            from ..sdk.tokens import estimate_tokens

            tokens: int | None = estimate_tokens(render(tools, fid).tool_block)
            source = "rendered"
        elif row is not None:
            tokens = int(round(row["schema"] * s.n_tools / 8))
            source = "study"
        else:
            return None, "study", None
        if row is None:
            return tokens, source, None
        default = CORE_DEFAULT_PROTOCOLS.get(fid)
        completion = row["completion"] if protocol_id == default else completion_tokens(ev, protocol_id)
        if completion is None:
            if s.objective == "cost":
                warnings.append(f"the study has no output length for {protocol_id}; {fid} with it has no cost")
            return tokens, source, None
        price = ev.load("cost")["data"]["prices"].get(s.price, {})
        overhead = row["prompt"] - row["schema"]
        prompt = int(round(tokens + overhead))
        cached = tokens if (price.get("schema_cached") and tokens is not None) else 0
        cost = cost_of(prompt, int(round(completion)), cached_tokens=cached, price=PRICES[s.price])
        return tokens, source, cost

    def _hidden_required(self, fid: str, tools: "Toolset") -> list[str]:
        from ..sdk.rendering import hidden_fields, render

        block = render(tools, fid).tool_block
        return [f"{h['tool']}.{h['path']}" for h in hidden_fields(tools, block) if h["required"]]

    # --------------------------------------------------------------- the rule
    def recommend(self, situation: Situation, *, tools: "Toolset | None" = None) -> Recommendation:
        """Recommend a format and protocol for ``situation``; ``tools`` gives real token counts."""
        s = situation
        s.validate()
        if tools is not None and len(tools) == 0:
            raise ValueError("the toolset is empty; give at least one tool")
        ev = self.evidence
        warnings: list[str] = []
        res = resolve_model(s.model, family=s.family, params_b=s.params_b, evidence=ev)
        tier = s.tier
        if tier > MAX_MEASURED_TIER:
            warnings.append(f"tier {tier} is outside the measured range 1 to 5; tier 5 is used")
            tier = MAX_MEASURED_TIER
        if s.n_tools > 256:
            warnings.append("more than 256 tools is outside the measured range; the 256-tool value is used")
        candidates = list(dict.fromkeys(s.candidates)) if s.candidates else list(CORE_FORMATS)
        for c in candidates:
            if c in TWO_STAGE_FORMATS:
                raise ValueError(f"{c} is a two-stage format; the catalogue advice covers two-stage disclosure")
        if any(c not in CORE_FORMATS for c in candidates):
            warnings.append(
                "candidates outside the eight core formats are scored from the site export, not from "
                "the paper's tables, with no count, tier or protocol shift"
            )
        family_row = ev.family_row(res.family) if res.family else None
        anchor_row = ev.anchor_row(res.anchor) if res.anchor else None
        checkpoint_row = ev.checkpoint_row(res.checkpoint) if res.checkpoint else None
        basis_note = ""
        if s.rule == "main":
            if res.anchor and anchor_row is not None:
                basis = f"anchor:{res.anchor}"
            elif checkpoint_row is not None:
                basis = f"checkpoint:{checkpoint_row['id']}"
            elif res.family and family_row is not None:
                basis = f"family:{res.family}"
                rng = family_row.get("params_range")
                n_ck = family_row.get("checkpoints")
                if n_ck:
                    size = (
                        f", {rng[0]:g} to {rng[1]:g}B"
                        if rng and rng[0] != rng[1]
                        else (f", {rng[0]:g}B" if rng else "")
                    )
                    basis_note = f"mean of {n_ck} checkpoint{'s' if n_ck != 1 else ''}{size}"
            else:
                basis = "pooled"
                if res.family and family_row is None:
                    warnings.append(f"no family evidence for {res.family}; using the pooled table")
        else:
            basis = "pooled"
            if (res.family and family_row is not None) or (res.anchor and anchor_row is not None):
                warnings.append("family evidence exists only under the main rule; using the pooled table")
        if s.rule != "main" and (s.n_tools != 8 or tier != 3):
            warnings.append(
                f"the tool-count and tier shifts come from main-rule tables and are applied under the "
                f"{s.rule.replace('_', '-')} rule"
            )

        scored = [x for x in (self._score(f, s, res, tier, tools, warnings) for f in candidates) if x is not None]
        if not scored:
            raise ValueError("no candidate format has evidence to score")
        if s.n_tools != 8 and tier != 3:
            dropped = any(x.tier_dropped for x in scored)
            warnings.append(
                f"no table crossed the tool count and the tier: tier {tier} was measured at 8 tools and "
                f"{s.n_tools} tools at tier 3"
                + ("; a tier gain is therefore not applied at this count" if dropped else "")
            )

        force_two_stage = False
        if s.token_budget is not None:
            fits = [x for x in scored if x.schema_tokens is None or x.schema_tokens <= s.token_budget]
            over = [x.format_id for x in scored if x not in fits]
            if over:
                warnings.append(f"over the token budget of {s.token_budget:,}: {', '.join(over)}")
            if not fits:
                last = next((x for x in scored if x.format_id == "json_minimal"), None) or self._score(
                    "json_minimal", s, res, tier, tools, warnings
                )
                assert last is not None
                fits = [last]
                force_two_stage = True
                if last.schema_tokens is not None and last.schema_tokens > s.token_budget:
                    warnings.append("no core format fits the budget; use two-stage disclosure")
                else:
                    warnings.append("only the minimal schema fits the budget; two-stage disclosure keeps full schemas")
            scored = fits

        context = s.context_tokens or res.context_tokens
        if context:
            too_big = [x for x in scored if x.schema_tokens is not None and x.schema_tokens > CONTEXT_SHARE * context]
            for x in too_big:
                x.penalty.append("context")
            if too_big:
                warnings.append(
                    f"over half of the {context:,}-token context window: "
                    f"{', '.join(x.format_id for x in too_big)}; ranked last"
                    + ("" if s.context_tokens else " (the window is the model zoo's max_model_len)")
                )
        if tools is not None:
            from ..sdk.rendering import non_identifier_names

            hidden_by = {x.format_id: self._hidden_required(x.format_id, tools) for x in scored}
            for x in scored:
                if hidden_by[x.format_id]:
                    x.penalty.append("hidden")
            hiders = [f for f, h in hidden_by.items() if h]
            if hiders:
                warnings.append(
                    f"{', '.join(hiders)} hide required nested fields of these tools "
                    f"({', '.join(hidden_by[hiders[0]][:4])}); ranked after the formats that show them"
                )
            odd = non_identifier_names(tools)
            if odd:
                warnings.append(
                    f"{', '.join(repr(n) for n in odd[:5])} {'is' if len(odd) == 1 else 'are'} not an "
                    f"identifier; code-signature formats write such names in snake case, which the "
                    f"parsers map back"
                )

        for x in scored:
            if s.objective == "cost":
                x.score = (x.expected / x.cost) if x.cost else float("-inf")
            else:
                x.score = x.expected
        if s.objective == "cost" and all(x.score == float("-inf") for x in scored):
            warnings.append("no candidate has a cost in the study's table; ranking by accuracy")
            for x in scored:
                x.score = x.expected
        order = {f: i for i, f in enumerate(candidates)}
        scored.sort(key=lambda x: (bool(x.penalty), -x.score, order.get(x.format_id, 99)))
        win = scored[0]
        rest = [x for x in scored[1:] if not x.penalty] if not win.penalty else scored[1:]
        if s.objective == "cost":
            tied = [x for x in rest if win.score > 0 and x.score >= win.score * (1 - TIE_SHARE)]
        else:
            tied = [x for x in rest if win.expected - x.expected <= TIE_POINTS]
        if win.kept_default is not None:
            best_p, gain = win.kept_default
            warnings.append(
                f"the pooled protocol table has {win.format_id} {gain:.1f} points higher with {best_p} "
                f"than with {win.protocol_id}, but that was not measured on this model, so "
                f"{win.protocol_id} is kept; pass protocol={best_p} to use it"
            )
        tied_group = [win] + tied
        cheapest = min(tied_group, key=lambda x: x.schema_tokens if x.schema_tokens is not None else 10**12)
        catalogue = catalogue_advice(
            s.n_tools, win.schema_tokens, context, ev, force_two_stage=force_two_stage, budget_tokens=s.token_budget
        )
        guard = _guard_advice(win.format_id, ev) if s.third_party_tools else None
        if win.protocol_id in TEXT_PROTOCOLS and s.rule == "main":
            f = ev.fact("renest_overcredit")
            iv = f.get("interval") or [None, None]
            warnings.append(
                f"{win.protocol_id} is a text protocol: under the main rule its parser re-nests a flat "
                f"argument, and a human check judged that repair wrong on {f['value']}% [{iv[0]}, {iv[1]}] "
                f"of the turns it touched; the symmetric rule applies the same repair to every protocol"
            )
        surface = None
        if res.params_b:
            from .surface import Surface

            rng = open_params_range(ev)
            if rng and not (rng[0] <= res.params_b <= rng[1]):
                warnings.append(
                    f"{res.params_b:g}B is outside the open checkpoints the surface was fitted on "
                    f"({rng[0]:g} to {rng[1]:g}B); the fitted surface is left out"
                )
            else:
                try:
                    sf = Surface(ev)
                    pred = sf.predict(win.format_id, params_b=res.params_b, n_tools=s.n_tools, tier=tier)
                    if pred is not None:
                        surface = {
                            "format_id": win.format_id,
                            "predicted_accuracy": round(pred, 2),
                            "params_b": res.params_b,
                            "form": sf.form,
                            "heldout_r2": sf.heldout_r2,
                            "note": f"held-out R² {sf.heldout_r2}; shown for extrapolation only",
                        }
                except Exception as exc:  # noqa: BLE001 - the surface is optional
                    log.warning("advisor: the fitted surface could not be read (%s)", exc)
                    surface = None
        ratio = ev.load("protocol_crossing")["data"]["ratios"].get(s.rule)
        fmt_meta = get_format(win.format_id).meta
        alternatives = [
            Alternative(
                format_id=x.format_id,
                format_name=get_format(x.format_id).meta.name,
                protocol_id=x.protocol_id,
                expected_accuracy=x.expected,
                schema_tokens=x.schema_tokens,
                cost_per_request=x.cost,
                score=x.score,
            )
            for x in scored[1:]
        ]
        thinking_off = (res.family in THINKING_FAMILIES) if res.family else False
        rec = Recommendation(
            format_id=win.format_id,
            format_name=fmt_meta.name,
            protocol_id=win.protocol_id,
            protocol_name=get_protocol(win.protocol_id).meta.name,
            expected_accuracy=win.expected,
            interval=win.interval,
            interval_kind="evidence_range",
            basis=basis if win.core else "pooled",
            rule=s.rule,
            objective=s.objective,
            schema_tokens=win.schema_tokens,
            tokens_source=win.tokens_source,
            cost_per_request=win.cost,
            tied_with=[x.format_id for x in tied],
            alternatives=alternatives,
            catalogue=catalogue,
            guard=guard,
            measure_hint=_measure_hint(ev, thinking_off),
            surface=surface,
            evidence=list(win.rows),
            explanation="",
            warnings=list(dict.fromkeys(warnings)),
            resolution=res,
            situation=s,
            evidence_version=ev.version,
            context_tokens=context,
            _base=win.base,
            _count_cells=win.count_cells,
            _tier_cells=win.tier_cells,
            _tier_dropped=win.tier_dropped,
            _protocol_cells=win.protocol_cells,
            _protocol_ratio=ratio if win.core else None,
            _family_best=(family_row or {}).get("best_format") if basis.startswith("family:") else None,
            _cheapest_tied=cheapest.format_id if tied else None,
            _basis_note=basis_note if win.core else "",
        )
        rec.explanation = explain(rec)
        return rec


def recommend(
    situation: Situation | None = None,
    *,
    tools: "Toolset | None" = None,
    evidence: Evidence | None = None,
    **fields: Any,
) -> Recommendation:
    """Recommend a format and protocol. ``fields`` are :class:`Situation` fields.

    ``recommend(model="Qwen/Qwen3-8B", n_tools=12)``. With ``tools``,
    ``n_tools`` and ``tier`` come from the tools unless given, and token counts
    come from rendering them. An empty toolset raises ``ValueError``.
    """
    if tools is not None and len(tools) == 0:
        raise ValueError("the toolset is empty; give at least one tool")
    if situation is None:
        kw = dict(fields)
        if tools is not None:
            kw.setdefault("n_tools", len(tools))
            kw.setdefault("tier", tools.tier_estimate())
        situation = Situation(**kw)
    elif fields:
        situation = replace(situation, **fields)
    return Advisor(evidence).recommend(situation, tools=tools)


__all__ = [
    "Advisor",
    "Alternative",
    "CatalogueAdvice",
    "GuardAdvice",
    "Recommendation",
    "catalogue_advice",
    "completion_tokens",
    "expit",
    "logit",
    "recommend",
    "table_pct",
]
