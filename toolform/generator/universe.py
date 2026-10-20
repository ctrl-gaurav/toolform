"""Building tool universes from the domain library.

This is the "novel generator" at the centre of the study. It turns a domain
spec plus a complexity tier into a :class:`~toolform.ir.ToolIR` with:

* a semantically coherent name and description,
* a parameter list whose shape is set by the tier (count, nesting, enums,
  unions, optional ratio),
* a binding plan that says where each underlying domain field lives inside
  that (possibly nested) argument structure,
* a kernel reference so the call is executable and therefore verifiable.

Universes are then assembled at a requested tool count by mixing the target
tool with distractors. Distractor choice matters: half come from the same
domain (near misses that share vocabulary) and half from other domains (far
misses). That mix is what makes tool-count scaling a real difficulty axis
rather than just a longer prompt.
"""

from __future__ import annotations

import random
from typing import Any

from ..ir import Constraints, ParamIR, ToolIR, ToolUniverse, TypeIR, TypeKind
from .domains import DomainSpec, FieldSpec, OpSpec, active_domains, get_domain
from .kernels import WorldState
from .version import current_version

# --------------------------------------------------------------------------- #
# complexity tiers
# --------------------------------------------------------------------------- #

TIERS: dict[int, dict[str, Any]] = {
    1: {
        "name": "minimal",
        "max_params": 2,
        "optional_budget": 0,
        "nesting": 0,
        "enums": 0,
        "unions": 0,
        "arrays": 0,
        "constraints": False,
        "long_descriptions": False,
    },
    2: {
        "name": "simple",
        "max_params": 4,
        "optional_budget": 1,
        "nesting": 0,
        "enums": 1,
        "unions": 0,
        "arrays": 0,
        "constraints": True,
        "long_descriptions": False,
    },
    3: {
        "name": "moderate",
        "max_params": 6,
        "optional_budget": 2,
        "nesting": 1,
        "enums": 1,
        "unions": 0,
        "arrays": 1,
        "constraints": True,
        "long_descriptions": True,
    },
    4: {
        "name": "complex",
        "max_params": 9,
        "optional_budget": 4,
        "nesting": 2,
        "enums": 2,
        "unions": 1,
        "arrays": 1,
        "constraints": True,
        "long_descriptions": True,
    },
    5: {
        "name": "extreme",
        "max_params": 12,
        "optional_budget": 6,
        "nesting": 3,
        "enums": 3,
        "unions": 2,
        "arrays": 2,
        "constraints": True,
        "long_descriptions": True,
    },
}

TIER_IDS = tuple(sorted(TIERS))


def tier_name(tier: int) -> str:
    return TIERS[tier]["name"]


# --------------------------------------------------------------------------- #
# field -> parameter
# --------------------------------------------------------------------------- #

_PSEUDO_FIELDS = {
    "record_id": FieldSpec("record_id", TypeKind.STRING, (), (), "Identifier of the record to act on."),
    "limit": FieldSpec("limit", TypeKind.INTEGER, (3, 5, 10), (), "How many results to return.", 1, 100),
}


def _field_of(domain: DomainSpec, name: str) -> FieldSpec:
    f = domain.field(name)
    if f is not None:
        return f
    if name in _PSEUDO_FIELDS:
        return _PSEUDO_FIELDS[name]
    return FieldSpec(name, TypeKind.STRING, (), (), f"Value for {name}.")


def _type_for(f: FieldSpec, tier_cfg: dict[str, Any]) -> TypeIR:
    if f.is_enum:
        return TypeIR.enum_of(list(f.enum))
    if f.kind == TypeKind.ARRAY:
        return TypeIR.array_of(TypeIR.string())
    c: dict[str, Any] = {}
    if tier_cfg["constraints"]:
        if f.minimum is not None:
            c["minimum"] = f.minimum
        if f.maximum is not None:
            c["maximum"] = f.maximum
    return TypeIR(kind=f.kind, constraints=Constraints(**c))


def _describe(f: FieldSpec, long: bool) -> str:
    base = f.description or f"The {f.name.replace('_', ' ')}."
    if long:
        extra = []
        if f.unit:
            extra.append(f"Measured in {f.unit}.")
        if f.is_enum:
            extra.append("Must be one of the listed choices.")
        if f.minimum is not None or f.maximum is not None:
            lo = "" if f.minimum is None else f"at least {f.minimum}"
            hi = "" if f.maximum is None else f"at most {f.maximum}"
            extra.append("Value must be " + " and ".join(x for x in (lo, hi) if x) + ".")
        return " ".join([base, *extra])
    return base


# --------------------------------------------------------------------------- #
# tool construction
# --------------------------------------------------------------------------- #


def build_tool(
    domain: DomainSpec,
    op: OpSpec,
    tier: int = 2,
    *,
    rng: random.Random | None = None,
    variant: int = 0,
) -> ToolIR:
    """Build one tool from a (domain, operation) pair at a complexity tier.

    ``variant`` lets one (domain, op) pair produce several distinct tools when
    a large universe needs more tools than the library has base pairs. Variants
    differ in which optional fields they expose, so they are genuine near
    misses rather than duplicates.
    """
    cfg = TIERS[tier]
    rng = rng or random.Random(f"{domain.name}:{op.verb}:{tier}:{variant}".__hash__() & 0xFFFFFF)

    req_names = list(op.required_fields)
    opt_names = list(op.optional_fields)
    v2 = current_version() == 2
    cfg_roles = dict(op.roles)
    if variant:
        # rotate the optional list so variants expose different extras
        k = variant % max(1, len(opt_names) or 1)
        opt_names = opt_names[k:] + opt_names[:k]
        if v2:
            # generator v2: a variant is behaviourally distinct, not a
            # re-cut of the same interface. It requires one field the base tool leaves
            # optional, and an update variant changes a different field (the kernel's role).
            if opt_names:
                promoted = opt_names.pop(0)
                req_names = req_names + [promoted]
            if op.kernel == "update":
                base_field = cfg_roles.get("field", "")
                others = [f.name for f in domain.fields if f.name not in req_names and f.name != base_field]
                if others:
                    cfg_roles["field"] = others[(variant - 1) % len(others)]
                    if cfg_roles["field"] not in req_names:
                        req_names = req_names + [cfg_roles["field"]]

    # trim to the tier budget
    req_names = req_names[: max(1, cfg["max_params"] - cfg["optional_budget"])]
    opt_names = opt_names[: cfg["optional_budget"]]

    # pad with unused domain fields when the tier allows more parameters
    used = set(req_names) | set(opt_names)
    spare = [f.name for f in domain.fields if f.name not in used]
    while len(req_names) + len(opt_names) < cfg["max_params"] and spare:
        opt_names.append(spare.pop(0))

    paths: dict[str, list[str]] = {}
    params: list[ParamIR] = []

    flat_specs = [(n, True) for n in req_names] + [(n, False) for n in opt_names]

    # decide which parameters get grouped into a nested object
    nest_depth = cfg["nesting"]
    grouped: list[tuple[str, bool]] = []
    if nest_depth >= 1 and len(flat_specs) >= 3:
        n_group = 2 if nest_depth == 1 else min(3, len(flat_specs) - 1)
        grouped = flat_specs[-n_group:]
        flat_specs = flat_specs[:-n_group]

    n_enum = 0
    n_union = 0
    n_array = 0
    for name, required in flat_specs:
        f = _field_of(domain, name)
        t = _type_for(f, cfg)
        if t.kind == TypeKind.ENUM:
            if n_enum >= cfg["enums"]:
                t = TypeIR.string()
            else:
                n_enum += 1
        if t.kind == TypeKind.ARRAY:
            if n_array >= cfg["arrays"]:
                t = TypeIR.string()
            else:
                n_array += 1
        if n_union < cfg["unions"] and f.kind == TypeKind.INTEGER and not required:
            t = TypeIR.union_of_types([TypeIR.integer(), TypeIR.string()])
            n_union += 1
        params.append(
            ParamIR(
                name=name,
                type=t,
                description=_describe(f, cfg["long_descriptions"]),
                required=required,
                default=_default_for(f) if not required else None,
                example=f.values[0] if f.values else None,
            )
        )
        paths[name] = [name]

    if grouped:
        group_name = _group_name(domain, op)
        inner: list[ParamIR] = []
        for name, required in grouped:
            f = _field_of(domain, name)
            t = _type_for(f, cfg)
            if t.kind == TypeKind.ENUM and n_enum >= cfg["enums"]:
                t = TypeIR.string()
            elif t.kind == TypeKind.ENUM:
                n_enum += 1
            inner.append(
                ParamIR(
                    name=name,
                    type=t,
                    description=_describe(f, cfg["long_descriptions"]),
                    required=required,
                )
            )
            paths[name] = [group_name, name]

        group_type = TypeIR.object_of(inner)
        if nest_depth >= 3 and len(inner) >= 2:
            # push the tail fields one level deeper
            deeper_name = "details"
            head, tail = inner[:1], inner[1:]
            group_type = TypeIR.object_of([*head, ParamIR(deeper_name, TypeIR.object_of(tail), "Extra detail.", False)])
            for p in tail:
                paths[p.name] = [group_name, deeper_name, p.name]

        params.append(
            ParamIR(
                name=group_name,
                type=group_type,
                description=f"Details of the {domain.entity}.",
                required=any(r for _, r in grouped),
            )
        )

    returns = TypeIR.object_of(
        [
            ParamIR("ok", TypeIR.boolean(), "Whether the call succeeded.", True),
            ParamIR("result", TypeIR(kind=TypeKind.ANY), "The value produced.", False),
        ]
    )

    if v2 and op.kernel == "create":
        # generator v2: an array of objects and a date on every create
        params.append(
            ParamIR(
                name="line_items",
                type=TypeIR.array_of(
                    TypeIR.object_of(
                        [
                            ParamIR("label", TypeIR.string(), "What the item is.", True),
                            ParamIR("count", TypeIR.integer(), "How many of it.", True),
                        ]
                    )
                ),
                description=f"Items attached to the {domain.entity}, each a label with a count.",
                required=False,
                example=[{"label": "starter", "count": 2}],
            )
        )
        params.append(
            ParamIR(
                name="due_on",
                type=TypeIR.string(format="date"),
                description=f"Date the {domain.entity} is due, YYYY-MM-DD.",
                required=False,
                example="2027-06-01",
            )
        )
        paths["line_items"] = ["line_items"]
        paths["due_on"] = ["due_on"]

    name = f"{domain.name}_{op.verb}" if not variant else f"{domain.name}_{op.verb}_v{variant}"
    cfg_roles.setdefault("key", req_names[0] if req_names else "")

    return ToolIR(
        name=name,
        description=_tool_description(domain, op, cfg["long_descriptions"]),
        params=tuple(params),
        returns=returns,
        returns_description=op.returns,
        domain=domain.name,
        category=op.kernel,
        tags=(domain.name, op.verb, f"tier{tier}"),
        kernel=op.kernel,
        kernel_args={
            "table": domain.name,
            "cfg": cfg_roles,
            "paths": paths,
            "tier": tier,
            "variant": variant,
            "templates": list(op.request_templates),
        },
        origin="synthetic",
    )


def _group_name(domain: DomainSpec, op: OpSpec) -> str:
    return f"{domain.entity}_details"


def _default_for(f: FieldSpec) -> Any:
    if f.is_enum:
        return f.enum[0]
    if f.values:
        return f.values[0]
    if f.kind == TypeKind.BOOLEAN:
        return False
    if f.kind == TypeKind.INTEGER:
        return 1
    if f.kind == TypeKind.NUMBER:
        return 1.0
    return None


def _tool_description(domain: DomainSpec, op: OpSpec, long: bool) -> str:
    base = op.description or f"{op.verb.replace('_', ' ').capitalize()} a {domain.entity}."
    if long:
        return f"{base} Works on the {domain.blurb} data set."
    return base


# --------------------------------------------------------------------------- #
# universe assembly
# --------------------------------------------------------------------------- #


def all_base_tools(tier: int = 2, *, max_variants: int = 4) -> list[ToolIR]:
    """Every tool the library can produce at a tier, base pairs then variants."""
    out: list[ToolIR] = []
    for d in active_domains():
        for op in d.ops:
            out.append(build_tool(d, op, tier))
    for v in range(1, max_variants):
        for d in active_domains():
            for op in d.ops:
                if len(op.optional_fields) + len(op.required_fields) > 1:
                    out.append(build_tool(d, op, tier, variant=v))
    return out


def chain_capable_domains(tier: int = 2) -> list[str]:
    """Domains that can support a chain on their own.

    A chain needs a producer (a ``create`` kernel) and a consumer (a tool that
    takes ``record_id``) in the *same* domain, or the follow-up turn is
    unanswerable. 13 of the 24 domains qualify.
    """
    by_domain: dict[str, list[ToolIR]] = {}
    for t in all_base_tools(tier):
        by_domain.setdefault(t.domain, []).append(t)
    out = []
    for domain, tools in by_domain.items():
        has_producer = any(t.kernel == "create" for t in tools)
        has_consumer = any(t.param("record_id") is not None for t in tools)
        if has_producer and has_consumer:
            out.append(domain)
    return sorted(out)


def _ensure_chain_pair(chosen: list[ToolIR], near: list[ToolIR], n_tools: int) -> list[ToolIR]:
    """Make sure the target domain's producer and consumer both made the cut.

    Picking ``near_ratio * n_tools`` tools at random from the target domain can
    still miss one of the two, so we swap the missing one in over a tool from
    another domain. At a single tool there is no room for a pair and the chain
    builder falls back, which it records in the instance metadata.
    """
    if n_tools < 2 or not near:
        return chosen
    # Both halves of the pair must come from the *target* domain. Checking
    # "is there a producer anywhere" would be satisfied by a producer in one
    # domain and a consumer in another, which is exactly the cross-domain pair
    # that makes a chain unanswerable.
    target_domain = near[0].domain
    have = {id(t) for t in chosen}
    for predicate in (
        lambda t: t.kernel == "create",
        lambda t: t.param("record_id") is not None,
    ):
        if any(predicate(t) for t in chosen if t.domain == target_domain):
            continue
        wanted = next((t for t in near if predicate(t)), None)
        if wanted is None or id(wanted) in have:
            continue
        # Replace a tool from another domain so the near/far balance holds.
        victim = next(
            (i for i in range(len(chosen) - 1, -1, -1) if chosen[i].domain != wanted.domain),
            None,
        )
        if victim is None:
            continue
        chosen[victim] = wanted
        have.add(id(wanted))
    return chosen


def make_universe(
    n_tools: int,
    *,
    tier: int = 2,
    seed: int = 0,
    target_domain: str | None = None,
    near_ratio: float = 0.5,
    naming: str = "semantic",
    universe_id: str | None = None,
    dedupe: bool = False,
) -> ToolUniverse:
    """Assemble a universe of ``n_tools`` tools.

    ``near_ratio`` is the share of distractors drawn from the same domain as
    the target. Higher values make selection harder without changing the
    prompt length, which lets us separate "too many tokens" from "too many
    similar options".

    ``dedupe`` keeps one tool per displayed interface: a
    variant whose rotation of optional fields cycled onto another's is
    replaced by the next unused tool, so no two tools shown differ only in
    name. Off by default, so universes drawn without it are reproduced exactly.

    The target domain is always drawn from the chain-capable ones, and a
    producer/consumer pair from it is guaranteed to be in the universe whenever
    there is room. Without that, whether a cell can express a chain at all is
    decided by the seed: at 16 tools half of all seeds produced a universe with
    no same-domain producer/consumer pair, every chain instance silently fell
    back to a single call, and the cell reported single-call accuracy under a
    "chain" label. Constraining the target domain also means all five regimes
    at one (n_tools, tier, seed) share the same universe, so a regime
    comparison is not confounded by the tool set.
    """
    rng = random.Random(f"universe:{n_tools}:{tier}:{seed}:{target_domain}")
    pool = all_base_tools(tier)
    by_domain: dict[str, list[ToolIR]] = {}
    for t in pool:
        by_domain.setdefault(t.domain, []).append(t)

    domains = sorted(by_domain)
    if target_domain is None:
        capable = chain_capable_domains(tier)
        target_domain = rng.choice(capable or domains)

    near = list(by_domain.get(target_domain, []))
    rng.shuffle(near)
    far = [t for t in pool if t.domain != target_domain]
    rng.shuffle(far)

    n_near = min(len(near), max(1, int(round(n_tools * near_ratio))))
    chosen = near[:n_near]
    chosen += far[: max(0, n_tools - len(chosen))]
    chosen = _ensure_chain_pair(chosen, near, n_tools)

    # if the library ran out, extend with higher variants
    v = 4
    while len(chosen) < n_tools:
        extra = []
        for d in active_domains():
            for op in d.ops:
                extra.append(build_tool(d, op, tier, variant=v))
        rng.shuffle(extra)
        chosen += extra[: n_tools - len(chosen)]
        v += 1
        if v > 40:  # pragma: no cover - safety valve
            break

    chosen = chosen[:n_tools]
    if dedupe:
        chosen = _dedupe_interfaces(chosen, near + far, tier, n_tools, rng)
    rng.shuffle(chosen)

    uid = universe_id or f"u{n_tools}t{tier}s{seed}"
    universe = ToolUniverse(
        tools=chosen,
        universe_id=uid,
        seed=seed,
        meta={
            "n_tools": n_tools,
            "tier": tier,
            "tier_name": tier_name(tier),
            "target_domain": target_domain,
            "near_ratio": near_ratio,
            "naming": naming,
        },
    )
    if naming != "semantic":
        from .naming import rename_universe

        universe = rename_universe(universe, naming, seed=seed)
    return universe


def _dedupe_interfaces(
    chosen: list[ToolIR], pool: list[ToolIR], tier: int, n_tools: int, rng: random.Random
) -> list[ToolIR]:
    """One tool per displayed interface, topped up from the pool and then
    from higher variants, in the pool's own (already shuffled) order."""
    seen: set[str] = set()
    out: list[ToolIR] = []
    names: set[str] = set()

    def take(t: ToolIR) -> bool:
        k = t.interface_key()
        if k in seen or t.name in names:
            return False
        seen.add(k)
        names.add(t.name)
        out.append(t)
        return True

    for t in chosen:
        take(t)
    for t in pool:
        if len(out) >= n_tools:
            break
        take(t)
    v = 4
    while len(out) < n_tools and v <= 40:
        extra = []
        for d in active_domains():
            for op in d.ops:
                extra.append(build_tool(d, op, tier, variant=v))
        rng.shuffle(extra)
        for t in extra:
            if len(out) >= n_tools:
                break
            take(t)
        v += 1
    if len(out) < n_tools:
        raise ValueError(
            f"the library has only {len(out)} distinct interfaces at tier {tier}; "
            f"{n_tools} were asked for with dedupe on"
        )
    return out[:n_tools]


# --------------------------------------------------------------------------- #
# world seeding
# --------------------------------------------------------------------------- #


def seed_world(universe: ToolUniverse, *, seed: int = 0, rows_per_domain: int = 8) -> WorldState:
    """Populate a deterministic world the universe's tools can operate on."""
    state = WorldState(seed=seed)
    # A universe derived from another by a treatment (a policy folded into one
    # description, an injected sentence) carries the original's fingerprint in
    # its meta, so it seeds the same world: the treated and untreated arms then
    # bind the same values and differ only in the treatment.
    fp = universe.meta.get("world_fingerprint") or universe.fingerprint()
    rng = random.Random(f"world:{seed}:{fp}")
    domains = sorted({t.kernel_args.get("table", t.domain) for t in universe})
    for dname in domains:
        try:
            d = get_domain(dname)
        except KeyError:
            continue
        rows = state.table(dname)
        for _ in range(rows_per_domain):
            rec: dict[str, Any] = {"id": state.next_id(dname[:3].upper())}
            for f in d.fields:
                rec[f.name] = _sample_field(f, rng)
            rows.append(rec)
    return state


def _sample_field(f: FieldSpec, rng: random.Random) -> Any:
    if f.is_enum:
        return rng.choice(list(f.enum))
    if f.kind == TypeKind.ARRAY and current_version() == 2:
        # generator v2: an array field holds a list, never one of its
        # values; v1 stored a scalar there (the ``values`` branch came first)
        return rng.sample(list(f.values), k=min(len(f.values), rng.randint(1, 3))) if f.values else []
    if f.values:
        return rng.choice(list(f.values))
    if f.kind == TypeKind.BOOLEAN:
        return rng.random() < 0.5
    if f.kind == TypeKind.INTEGER:
        lo = int(f.minimum) if f.minimum is not None else 0
        hi = int(f.maximum) if f.maximum is not None else lo + 100
        return rng.randint(lo, max(lo, hi))
    if f.kind == TypeKind.NUMBER:
        lo = f.minimum if f.minimum is not None else 0.0
        hi = f.maximum if f.maximum is not None else lo + 100.0
        return round(rng.uniform(lo, hi), 2)
    if f.kind == TypeKind.ARRAY:
        # generator v2: the array field is filled, one to three values
        if current_version() == 2 and f.values:
            return rng.sample(list(f.values), k=min(len(f.values), rng.randint(1, 3)))
        return []
    return f"{f.name}_{rng.randint(1, 99)}"


# --------------------------------------------------------------------------- #
# argument nesting helpers (shared with the task generator and the grader)
# --------------------------------------------------------------------------- #


def nest_arguments(tool: ToolIR, flat: dict[str, Any]) -> dict[str, Any]:
    """Place flat field values into the tool's (possibly nested) arg structure."""
    paths: dict[str, list[str]] = tool.kernel_args.get("paths", {})
    out: dict[str, Any] = {}
    for field_name, value in flat.items():
        path = paths.get(field_name, [field_name])
        cur = out
        for key in path[:-1]:
            cur = cur.setdefault(key, {})
        cur[path[-1]] = value
    return out


def flatten_arguments(tool: ToolIR, args: dict[str, Any]) -> dict[str, Any]:
    """Inverse of :func:`nest_arguments`, tolerant of a flat model answer."""
    paths: dict[str, list[str]] = tool.kernel_args.get("paths", {})
    out: dict[str, Any] = {}
    for field_name, path in paths.items():
        cur: Any = args
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok:
            out[field_name] = cur
        elif field_name in args:  # model flattened a nested argument
            out[field_name] = args[field_name]
    for k, v in args.items():
        if k not in out and not isinstance(v, dict):
            out.setdefault(k, v)
    return out
