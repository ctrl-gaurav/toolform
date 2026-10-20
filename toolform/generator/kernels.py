"""Executable semantics for generated tools.

Every generated tool is backed by one of a small set of kernels operating on a
seeded :class:`WorldState`. That is what makes the benchmark verifiable rather
than merely plausible: we can execute the gold call, execute the model's call,
and compare both the returned value and the resulting world state.

Kernels are deliberately simple and total — they never raise for ordinary bad
input, they return a typed error record instead. The error-recovery task
regime depends on that.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable

Record = dict[str, Any]


@dataclass
class WorldState:
    """Deterministic store the kernels read and write.

    Seeded from the universe seed, so a run is reproducible and two runs with
    the same seed produce identical gold answers.
    """

    seed: int = 0
    tables: dict[str, list[Record]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    def table(self, name: str) -> list[Record]:
        return self.tables.setdefault(name, [])

    def next_id(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}-{n:04d}"

    def snapshot(self) -> str:
        """Stable hash of the whole state, used for end-state comparison."""
        payload = json.dumps(
            {k: sorted(json.dumps(r, sort_keys=True, default=str) for r in v) for k, v in sorted(self.tables.items())},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def clone(self) -> "WorldState":
        return WorldState(
            seed=self.seed,
            tables={k: [dict(r) for r in v] for k, v in self.tables.items()},
            counters=dict(self.counters),
            log=list(self.log),
        )


@dataclass
class KernelResult:
    ok: bool
    value: Any = None
    error: str | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, "result": self.value}
        return {"ok": False, "error": self.error, "error_type": self.error_type}


def _stable_int(text: str) -> int:
    """A process-independent integer for a string (the built-in hash is salted)."""
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def _err(kind: str, msg: str) -> KernelResult:
    return KernelResult(ok=False, error=msg, error_type=kind)


# --------------------------------------------------------------------------- #
# kernels
# --------------------------------------------------------------------------- #


def k_create(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    rec = {k: v for k, v in args.items() if v is not None}
    rec["id"] = state.next_id(table[:3].upper())
    state.table(table).append(rec)
    return KernelResult(ok=True, value={"id": rec["id"], "created": True})


def k_lookup(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    key = cfg.get("key")
    wanted = args.get(key) if key else None
    if wanted is None:
        # fall back to the first supplied scalar argument
        for v in args.values():
            if isinstance(v, (str, int, float)):
                wanted = v
                break
    for rec in state.table(table):
        if any(str(v) == str(wanted) for v in rec.values()):
            return KernelResult(ok=True, value=dict(rec))
    return _err("not_found", f"no {table} record matching {wanted!r}")


def k_search(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    rows = state.table(table)
    out = []
    for rec in rows:
        if all(str(rec.get(k)) == str(v) for k, v in args.items() if v is not None and k in rec):
            out.append(dict(rec))
    return KernelResult(ok=True, value={"count": len(out), "records": out[:20]})


def k_update(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    rid = args.get("record_id")
    field_name = cfg.get("field")
    if rid is None:
        return _err("missing_argument", "record_id is required")
    for rec in state.table(table):
        if rec.get("id") == rid:
            if field_name and field_name in args:
                rec[field_name] = args[field_name]
            for k, v in args.items():
                if k not in ("record_id",) and v is not None:
                    rec[k] = v
            return KernelResult(ok=True, value=dict(rec))
    return _err("not_found", f"no {table} record with id {rid!r}")


def k_delete(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    rid = args.get("record_id")
    rows = state.table(table)
    for i, rec in enumerate(rows):
        if rec.get("id") == rid:
            rows.pop(i)
            return KernelResult(ok=True, value={"removed": rid})
    return _err("not_found", f"no {table} record with id {rid!r}")


def k_count(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    res = k_search(state, table, args, cfg)
    if not res.ok:
        return res
    return KernelResult(ok=True, value={"count": res.value["count"]})


def k_aggregate(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    field_name = cfg.get("field")
    agg = cfg.get("agg", "sum")
    res = k_search(state, table, {k: v for k, v in args.items() if k != field_name}, cfg)
    if not res.ok:
        return res
    vals = [float(r[field_name]) for r in res.value["records"] if isinstance(r.get(field_name), (int, float))]
    if not vals:
        return KernelResult(ok=True, value={"aggregate": agg, "value": 0, "n": 0})
    if agg == "sum":
        v = sum(vals)
    elif agg == "mean":
        v = sum(vals) / len(vals)
    elif agg == "max":
        v = max(vals)
    elif agg == "min":
        v = min(vals)
    else:
        return _err("bad_argument", f"unknown aggregate {agg!r}")
    return KernelResult(ok=True, value={"aggregate": agg, "value": round(v, 4), "n": len(vals)})


def k_rank(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    field_name = cfg.get("field")
    order = cfg.get("order", "desc")
    limit = int(args.get("limit") or 3)
    res = k_search(state, table, {k: v for k, v in args.items() if k != "limit"}, cfg)
    if not res.ok:
        return res
    rows = [r for r in res.value["records"] if isinstance(r.get(field_name), (int, float))]
    rows.sort(key=lambda r: r[field_name], reverse=(order == "desc"))
    return KernelResult(ok=True, value={"ranked": rows[:limit], "by": field_name, "order": order})


_RATES = {"USD": 1.0, "EUR": 1.09, "GBP": 1.27, "JPY": 0.0067}
_TEMP_TO_C = {
    "celsius": lambda v: v,
    "fahrenheit": lambda v: (v - 32.0) * 5.0 / 9.0,
    "kelvin": lambda v: v - 273.15,
}


def k_convert(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    src = cfg.get("from")
    unit = args.get(src)
    if unit in _RATES:
        amount = float(args.get("amount", 0))
        return KernelResult(ok=True, value={"usd": round(amount * _RATES[unit], 4), "from": unit})
    if unit in _TEMP_TO_C:
        temp = float(args.get("temperature", 0))
        return KernelResult(ok=True, value={"celsius": round(_TEMP_TO_C[unit](temp), 4), "from": unit})
    return _err("bad_argument", f"cannot convert from {unit!r}")


def k_compute(state: WorldState, table: str, args: dict[str, Any], cfg: dict[str, Any]) -> KernelResult:
    op = cfg.get("op")
    if op == "distance":
        # A stable seed: Python's str hash is salted per process, so the
        # distance a deterministic kernel returned used to differ between
        # runs. sha256 of the sorted arguments instead.
        rnd = random.Random(_stable_int(json.dumps(args, sort_keys=True, default=str)) & 0xFFFF)
        km = round(500 + rnd.random() * 12000, 1)
        if str(args.get("units", "km")).startswith("mile"):
            km = round(km * 0.621371, 1)
        return KernelResult(ok=True, value={"distance": km, "units": args.get("units", "km")})
    if op == "forecast":
        days = int(args.get("days_ahead", 0))
        base = 12.0 + (_stable_int(str(args.get("city"))) % 15)
        return KernelResult(
            ok=True,
            value={"temperature": round(base + days * 0.4, 1), "days_ahead": days},
        )
    return _err("bad_argument", f"unknown computation {op!r}")


KERNELS: dict[str, Callable[..., KernelResult]] = {
    "create": k_create,
    "lookup": k_lookup,
    "search": k_search,
    "update": k_update,
    "delete": k_delete,
    "count": k_count,
    "aggregate": k_aggregate,
    "rank": k_rank,
    "convert": k_convert,
    "compute": k_compute,
}


def execute(
    state: WorldState,
    kernel: str,
    table: str,
    args: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> KernelResult:
    fn = KERNELS.get(kernel)
    if fn is None:
        return _err("unknown_kernel", f"no kernel named {kernel!r}")
    try:
        return fn(state, table, dict(args), dict(cfg or {}))
    except Exception as exc:  # noqa: BLE001 - kernels must never crash a run
        return _err("kernel_error", f"{type(exc).__name__}: {exc}")
