"""The study's evidence, shipped as JSON beside the code.

Every number the advisor, the CLI, the HTTP API and the dashboard show comes
from these files. They are built from the study's tables; nobody types a result
into them by hand, and every headline fact is checked against the paper.
"""

from __future__ import annotations

import functools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..sdk.errors import EvidenceError

DATA_DIR: Path = Path(__file__).parent / "data"

EVIDENCE_FILES: tuple[str, ...] = (
    "manifest",
    "facts",
    "formats",
    "protocols",
    "core_main",
    "families",
    "protocol_crossing",
    "tool_count",
    "tiers",
    "cost",
    "injection",
    "disclosure",
    "selection",
    "ladder",
    "zoo",
    "surface",
    "sample_renders",
    "render_cases",
    "advisor_cases",
    "guard_cases",
)

MEASURED_COUNTS: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 128, 256)


@dataclass(frozen=True)
class EvidenceRow:
    """One number the advisor rests on, with the table it came from."""

    source: str
    label: str
    value: float | None
    unit: str = "%"
    interval: tuple[float, float] | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "source": self.source,
            "label": self.label,
            "value": None if self.value is None else round(float(self.value), 4),
            "unit": self.unit,
            "interval": list(self.interval) if self.interval else None,
            "note": self.note,
        }


class Evidence:
    """Read access to the evidence files, with the lookups the advisor needs."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self._cache: dict[str, Any] = {}

    def load(self, name: str) -> Any:
        """One evidence file, parsed and cached. Unknown or missing files raise :class:`EvidenceError`."""
        if name not in EVIDENCE_FILES:
            raise EvidenceError(f"unknown evidence file {name!r}; known: {', '.join(EVIDENCE_FILES)}")
        if name not in self._cache:
            path = self.data_dir / f"{name}.json"
            if not path.is_file():
                raise EvidenceError(f"evidence file {path} is missing; reinstall toolform")
            try:
                self._cache[name] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise EvidenceError(f"evidence file {path} is not valid JSON: {exc}") from exc
        return self._cache[name]

    def _data(self, name: str) -> Any:
        return self.load(name)["data"]

    @property
    def version(self) -> str:
        """The evidence version, a build date plus a counter."""
        return str(self.load("manifest")["evidence_version"])

    def files(self) -> list[dict[str, Any]]:
        """The manifest's list of files with their sources and hashes."""
        return list(self.load("manifest")["files"])

    # ------------------------------------------------------------------ facts
    def facts(self) -> list[dict[str, Any]]:
        """Every headline fact."""
        return list(self._data("facts"))

    def fact(self, fact_id: str) -> dict[str, Any]:
        """One headline fact by id."""
        for f in self._data("facts"):
            if f["id"] == fact_id:
                return f
        raise EvidenceError(f"no fact {fact_id!r}")

    def fact_value(self, fact_id: str) -> float:
        """The value of one headline fact."""
        return float(self.fact(fact_id)["value"])

    # ---------------------------------------------------------------- formats
    def format_meta(self, format_id: str) -> dict[str, Any]:
        """A format's registry entry and its measured row from the site export."""
        table = self._data("formats")
        if format_id not in table:
            raise EvidenceError(f"no format {format_id!r} in the evidence")
        return table[format_id]

    def protocol_meta(self, protocol_id: str) -> dict[str, Any]:
        """A protocol's registry entry."""
        table = self._data("protocols")
        if protocol_id not in table:
            raise EvidenceError(f"no protocol {protocol_id!r} in the evidence")
        return table[protocol_id]

    # --------------------------------------------------------------- families
    def family_row(self, family_key: str) -> dict[str, Any] | None:
        """The open-weight family row of tab_models_main, or None."""
        for r in self._data("families")["rows"]:
            if r["kind"] == "open" and r["family"] == family_key:
                return r
        return None

    def anchor_row(self, name: str) -> dict[str, Any] | None:
        """An anchor model's row of tab_models_main by its label, or None."""
        for r in self._data("families")["rows"]:
            if r["kind"] != "open" and r["label"] == name:
                return r
        return None

    def checkpoint_row(self, model_id: str) -> dict[str, Any] | None:
        """One open-weight checkpoint's own row of tab_models_full, by its exact id (case ignored), or None."""
        want = model_id.lower()
        for r in self._data("families").get("checkpoints", []):
            if r["id"].lower() == want:
                return r
        return None

    def checkpoints_of(self, family_key: str) -> list[dict[str, Any]]:
        """The checkpoints behind one family row."""
        return [r for r in self._data("families").get("checkpoints", []) if r["family"] == family_key]

    def anchor_rows(self) -> list[dict[str, Any]]:
        """Every anchor row."""
        return [r for r in self._data("families")["rows"] if r["kind"] != "open"]

    # ------------------------------------------------------------ core tables
    def core_accuracy(self, format_id: str, rule: str = "main") -> float:
        """Main-grid accuracy of a core format under a rule (tab_main)."""
        by_rule = self._data("core_main")["by_rule"]
        if rule not in by_rule:
            raise EvidenceError(f"no rule {rule!r} in core_main")
        if format_id not in by_rule[rule]:
            raise EvidenceError(f"format {format_id!r} is not one of the eight core formats")
        return float(by_rule[rule][format_id])

    def _interp(self, series: list[float], n_tools: int) -> tuple[float, bool]:
        counts = self._data("tool_count")["counts"]
        if n_tools <= counts[0]:
            return float(series[0]), n_tools < counts[0]
        if n_tools >= counts[-1]:
            return float(series[-1]), n_tools > counts[-1]
        x = math.log2(n_tools)
        for i in range(len(counts) - 1):
            a, b = counts[i], counts[i + 1]
            if a <= n_tools <= b:
                xa, xb = math.log2(a), math.log2(b)
                t = 0.0 if xb == xa else (x - xa) / (xb - xa)
                return float(series[i] + t * (series[i + 1] - series[i])), False
        return float(series[-1]), True  # pragma: no cover

    def count_accuracy(self, format_id: str, n_tools: int) -> tuple[float, bool]:
        """Accuracy at a tool count (tab_count_by_format), linear in log2(n) between measured
        counts; ``clamped`` is True outside 1 to 256."""
        acc = self._data("tool_count")["accuracy"]
        if format_id not in acc:
            raise EvidenceError(f"format {format_id!r} has no tool-count curve")
        return self._interp(acc[format_id], n_tools)

    def empty_share(self, format_id: str, n_tools: int) -> tuple[float, bool]:
        """Share of empty turns at a tool count, interpolated like :meth:`count_accuracy`."""
        emp = self._data("tool_count")["empty"]
        if format_id not in emp:
            raise EvidenceError(f"format {format_id!r} has no empty-turn curve")
        return self._interp(emp[format_id], n_tools)

    def tier_accuracy(self, format_id: str, tier: int) -> float:
        """Accuracy at a complexity tier, 1 to 5 (tab_tier_by_format); outside that, the nearest tier."""
        acc = self._data("tiers")["accuracy"]
        if format_id not in acc:
            raise EvidenceError(f"format {format_id!r} has no tier curve")
        t = min(5, max(1, int(tier)))
        return float(acc[format_id][t - 1])

    def crossing(self, rule: str, format_id: str, protocol_id: str) -> float | None:
        """Accuracy of a format paired with a protocol under a rule (tab_protocol), or None."""
        cells = self._data("protocol_crossing")["rules"].get(rule, {}).get("cells", {})
        v = cells.get(format_id, {}).get(protocol_id)
        return None if v is None else float(v)

    def cost_row(self, format_id: str) -> dict[str, Any] | None:
        """The format's row of tab_cost, or None."""
        for r in self._data("cost")["rows"]:
            if r["format_id"] == format_id:
                return r
        return None

    def injection_row(self, format_id: str) -> dict[str, Any] | None:
        """The format's row of tab_pressure, or None."""
        for r in self._data("injection")["formats"]:
            if r["format_id"] == format_id:
                return r
        return None

    def disclosure_rows(self, n_tools: int) -> list[dict[str, Any]]:
        """The second two-stage design's rows at the measured count nearest ``n_tools`` (in log2; a tie
        goes to the larger count)."""
        rows = self._data("disclosure")["second_design"]
        counts = sorted({r["n_tools"] for r in rows})
        if not counts:
            return []
        target = min(counts, key=lambda c: (abs(math.log2(max(1, n_tools)) - math.log2(c)), -c))
        return [r for r in rows if r["n_tools"] == target]

    def selection(self) -> dict[str, Any]:
        """The selection comparison (tab_selection)."""
        return dict(self._data("selection"))


@functools.lru_cache(maxsize=4)
def _cached(data_dir: str | None) -> Evidence:
    return Evidence(Path(data_dir) if data_dir else None)


def load_evidence(data_dir: str | None = None) -> Evidence:
    """A cached :class:`Evidence` for the shipped data, or for ``data_dir``."""
    return _cached(str(data_dir) if data_dir is not None else None)


load_evidence.cache_clear = _cached.cache_clear  # type: ignore[attr-defined]


__all__ = ["DATA_DIR", "EVIDENCE_FILES", "Evidence", "EvidenceRow", "MEASURED_COUNTS", "load_evidence"]
