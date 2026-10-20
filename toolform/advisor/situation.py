"""The inputs of a recommendation, and resolving a model name to the study's evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from typing import Any, Mapping

from ..formats import has_format
from ..protocols import protocol_ids
from ..sdk.constants import RULES
from ..sdk.cost import PRICES
from .evidence import Evidence, load_evidence

OBJECTIVES: tuple[str, ...] = ("accuracy", "cost")

#: Regular expressions on the lower-cased model id, tried in order, to a zoo family.
#: Written into zoo.json so the website's port reads the same list.
FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"llama-xlam|watt-tool|hermes-3-llama|toolace|hammer", "llama3-tool"),
    (r"xlam", "xlam"),
    (r"qwen3\.5|qwen3_5|qwen35", "qwen3.5"),
    (r"qwen2\.5-coder", "qwen2.5-coder"),
    (r"qwen2\.5", "qwen2.5"),
    (r"qwen3", "qwen3"),
    (r"gemma-?4", "gemma4"),
    (r"gemma-?3", "gemma3"),
    (r"deepseek-r1-distill", "deepseek-r1"),
    (r"gpt-oss", "gpt-oss"),
    (r"glm", "glm"),
    (r"mistral|ministral|magistral|devstral", "mistral"),
    (r"phi-?\d|/phi", "phi"),
    (r"smollm", "smollm"),
    (r"llama", "llama3"),
)

#: Zoo families that share another family's evidence row.
FAMILY_ALIASES: dict[str, str] = {"qwen3-quant": "qwen3"}

#: Qwen 3.5 checkpoints this size or larger use the large-model row.
QWEN35_LARGE_B = 100.0

EFFORT_PREFERENCE: tuple[str | None, ...] = ("medium", "none", None, "low", "high")


def _fold(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_params_b(model_id: str) -> float | None:
    """The largest ``<number>b`` token in a model id, in billions (``122b-a10b`` gives 122)."""
    sizes = [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)b(?![a-z0-9])", model_id.lower())]
    return max(sizes) if sizes else None


@dataclass
class Situation:
    """What the advisor needs to know. Every field has a default."""

    model: str | None = None
    family: str | None = None
    params_b: float | None = None
    n_tools: int = 8
    tier: int = 3
    token_budget: int | None = None
    context_tokens: int | None = None
    objective: str = "accuracy"
    price: str = "frontier_api"
    rule: str = "main"
    protocol: str | None = None
    candidates: tuple[str, ...] | None = None
    third_party_tools: bool = False

    def validate(self) -> None:
        """Raise ``ValueError`` naming the first bad field."""

        def bad(name: str, why: str) -> ValueError:
            return ValueError(f"situation.{name}: {why}")

        if self.model is not None and not isinstance(self.model, str):
            raise bad("model", "must be a string or None")
        if self.family is not None and not isinstance(self.family, str):
            raise bad("family", "must be a string or None")
        if self.params_b is not None and (
            isinstance(self.params_b, bool)
            or not isinstance(self.params_b, (int, float))
            or not math.isfinite(self.params_b)
            or self.params_b <= 0
        ):
            raise bad("params_b", "must be a positive, finite number of billions")
        for name in ("n_tools", "tier"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise bad(name, "must be a whole number of at least 1")
        for name in ("token_budget", "context_tokens"):
            v = getattr(self, name)
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
                raise bad(name, "must be a whole number of at least 1, or None")
        if self.objective not in OBJECTIVES:
            raise bad("objective", f"must be one of {', '.join(OBJECTIVES)}")
        if self.price not in PRICES:
            raise bad("price", f"must be one of {', '.join(PRICES)}")
        if self.rule not in RULES:
            raise bad("rule", f"must be one of {', '.join(RULES)}")
        if self.protocol is not None and self.protocol not in protocol_ids():
            raise bad("protocol", f"unknown protocol {self.protocol!r}")
        if self.candidates is not None:
            if not isinstance(self.candidates, (tuple, list)) or not self.candidates:
                raise bad("candidates", "must be a non-empty list of format ids, or None")
            for c in self.candidates:
                if not isinstance(c, str) or not has_format(c):
                    raise bad("candidates", f"unknown format {c!r}")
        if not isinstance(self.third_party_tools, bool):
            raise bad("third_party_tools", "must be true or false")

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["candidates"] = list(self.candidates) if self.candidates is not None else None
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Situation":
        """Build from a dict; unknown keys are ignored, bad types raise ``ValueError``."""
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in dict(d).items() if k in known}
        if isinstance(kwargs.get("candidates"), list):
            kwargs["candidates"] = tuple(kwargs["candidates"])
        s = cls(**kwargs)
        s.validate()
        return s


@dataclass
class ModelResolution:
    """What the study knows about a model name."""

    query: str | None
    family: str | None
    family_label: str | None
    anchor: str | None
    params_b: float | None
    kind: str | None
    context_tokens: int | None
    matched_by: str
    checkpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _zoo(evidence: Evidence) -> dict[str, Any]:
    return evidence.load("zoo")["data"]


def family_label(family: str | None, evidence: Evidence) -> str | None:
    """The table label of a zoo family ("Qwen 3" for ``qwen3``), or None."""
    if not family:
        return None
    fam = _zoo(evidence).get("families", {}).get(family)
    return fam.get("label") if fam else None


def _anchor_match(query: str, evidence: Evidence) -> str | None:
    q = _fold(query)
    if not q:
        return None
    rows = evidence.anchor_rows()
    contained = [r["label"] for r in rows if _fold(r["label"]) and _fold(r["label"]) in q]
    if contained:
        return max(contained, key=lambda lbl: len(_fold(lbl)))
    base_hits = []
    for r in rows:
        base = re.sub(r"\s*\([^)]*\)\s*$", "", r["label"])
        if _fold(base) == q:
            base_hits.append(r)
    if not base_hits:
        return None

    def pref(r: dict[str, Any]) -> int:
        e = r.get("effort")
        return EFFORT_PREFERENCE.index(e) if e in EFFORT_PREFERENCE else len(EFFORT_PREFERENCE)

    return min(base_hits, key=pref)["label"]


def _pattern_family(model_id: str, params_b: float | None) -> str | None:
    low = model_id.lower()
    for rx, fam in FAMILY_PATTERNS:
        if re.search(rx, low):
            if fam == "qwen3.5" and params_b is not None and params_b >= QWEN35_LARGE_B:
                return "qwen3.5-large"
            return fam
    return None


def resolve_model(
    model: str | None, *, family: str | None = None, params_b: float | None = None, evidence: Evidence | None = None
) -> ModelResolution:
    """Match a model name to the study's evidence.

    First match wins: an explicit ``family``; an anchor model of
    tab_models_main (names folded to lower-case letters and digits; an
    effort-less name prefers the medium row); a checkpoint of
    tab_models_full by its exact id, which carries its own row and its
    family; an exact id of the model zoo; the regular expressions of
    :data:`FAMILY_PATTERNS`; nothing, in which case the advisor uses the
    pooled tables. Parameters come from the zoo, else from the largest
    ``<n>b`` in the id.
    """
    ev = evidence or load_evidence()
    zoo = _zoo(ev)
    by_id = {m["id"].lower(): m for m in zoo.get("models", [])}
    entry = by_id.get(model.lower()) if model else None
    zoo_params = entry.get("params_b") if entry else None
    parsed = parse_params_b(model) if model else None
    size = params_b if params_b is not None else (zoo_params if zoo_params is not None else parsed)
    kind = entry.get("kind") if entry else None
    ctx = entry.get("max_model_len") if entry else None

    if family:
        fam = FAMILY_ALIASES.get(family, family)
        return ModelResolution(
            query=model,
            family=fam,
            family_label=family_label(fam, ev),
            anchor=None,
            params_b=size,
            kind=kind,
            context_tokens=ctx,
            matched_by="family",
        )
    if model:
        anchor = _anchor_match(model, ev)
        if anchor:
            return ModelResolution(
                query=model,
                family=None,
                family_label=None,
                anchor=anchor,
                params_b=size,
                kind=kind,
                context_tokens=ctx,
                matched_by="anchor",
            )
        cp = ev.checkpoint_row(model)
        if cp is not None:
            fam = cp["family"]
            return ModelResolution(
                query=model,
                family=fam,
                family_label=family_label(fam, ev),
                anchor=None,
                params_b=size,
                kind=kind,
                context_tokens=ctx,
                matched_by="checkpoint",
                checkpoint=cp["id"],
            )
        if entry is not None:
            zoo_fam = entry.get("family")
            fam_z = FAMILY_ALIASES.get(zoo_fam, zoo_fam) if zoo_fam else None
            return ModelResolution(
                query=model,
                family=fam_z,
                family_label=family_label(fam_z, ev),
                anchor=None,
                params_b=size,
                kind=kind,
                context_tokens=ctx,
                matched_by="zoo",
            )
        fam_p = _pattern_family(model, size)
        if fam_p:
            return ModelResolution(
                query=model,
                family=fam_p,
                family_label=family_label(fam_p, ev),
                anchor=None,
                params_b=size,
                kind=None,
                context_tokens=None,
                matched_by="pattern",
            )
    return ModelResolution(
        query=model,
        family=None,
        family_label=None,
        anchor=None,
        params_b=size,
        kind=None,
        context_tokens=None,
        matched_by="none",
    )


__all__ = [
    "FAMILY_ALIASES",
    "FAMILY_PATTERNS",
    "ModelResolution",
    "OBJECTIVES",
    "QWEN35_LARGE_B",
    "Situation",
    "family_label",
    "parse_params_b",
    "resolve_model",
]
