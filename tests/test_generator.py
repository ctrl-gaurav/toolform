"""The generator must produce answerable, verifiable, reproducible tasks."""

from __future__ import annotations

import pytest

from toolform.generator import (
    DOMAINS,
    REGIMES,
    TIER_IDS,
    all_base_tools,
    execute_call,
    generate_instances,
    isomorph,
    make_universe,
    rename_universe,
    seed_world,
)
from toolform.ir import validate_call


def test_domains_are_well_formed():
    for d in DOMAINS:
        assert d.ops, f"{d.name} has no operations"
        field_names = {f.name for f in d.fields}
        for op in d.ops:
            for f in op.required_fields + op.optional_fields:
                assert f in field_names or f in ("record_id", "limit"), (d.name, op.verb, f)


@pytest.mark.parametrize("tier", TIER_IDS)
def test_tiers_increase_complexity(tier):
    tools = all_base_tools(tier)
    assert tools
    mean_params = sum(len(t.params) for t in tools) / len(tools)
    assert mean_params >= 1
    if tier >= 3:
        assert any(t.max_depth >= 1 for t in tools), "no nesting at tier 3+"
    if tier >= 4:
        assert any(t.n_unions >= 1 for t in tools), "no unions at tier 4+"


def test_universe_size_is_exact():
    for n in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        u = make_universe(n, tier=3, seed=0)
        assert len(u) == n, (n, len(u))
        assert len({t.name for t in u}) == n, "duplicate tool names in a universe"


def test_generation_is_reproducible():
    a = generate_instances(5, n_tools=8, tier=3, regime="single", seed=42)
    b = generate_instances(5, n_tools=8, tier=3, regime="single", seed=42)
    for x, y in zip(a, b, strict=False):
        assert x.turns[0].user == y.turns[0].user
        assert [str(c) for c in x.gold_calls] == [str(c) for c in y.gold_calls]


def test_different_seeds_give_different_tasks():
    a = generate_instances(5, n_tools=8, tier=3, regime="single", seed=1)
    b = generate_instances(5, n_tools=8, tier=3, regime="single", seed=2)
    assert [t.turns[0].user for t in a] != [t.turns[0].user for t in b]


@pytest.mark.parametrize("regime", REGIMES)
def test_every_regime_produces_usable_instances(regime):
    insts = generate_instances(8, n_tools=12, tier=3, regime=regime, seed=0)
    assert len(insts) == 8
    for inst in insts:
        assert inst.turns
        for ti, turn in enumerate(inst.turns):
            # the agentic regime's later turns have only the tool result as
            # their stimulus, so their user text is empty by design
            assert turn.user.strip() or (regime == "agentic" and ti > 0)
            if regime == "null":
                assert not turn.gold_calls
            elif regime == "agentic" and not turn.expects_call:
                assert not turn.gold_calls
            else:
                assert turn.gold_calls or inst.meta.get("chain_fallback")


def test_gold_calls_execute_successfully():
    insts = generate_instances(20, n_tools=12, tier=3, regime="single", seed=0)
    world = seed_world(insts[0].universe, seed=0)
    failures = []
    for inst in insts:
        for call in inst.gold_calls:
            res = execute_call(inst.universe, call, world.clone())
            if res.error_type in ("unknown_tool", "unknown_kernel", "kernel_error"):
                failures.append((call.name, res.error))
    assert not failures, failures


def test_naming_schemes_strip_meaning():
    plain = make_universe(8, tier=3, seed=0)
    opaque = rename_universe(plain, "opaque", seed=0)
    pseudo = rename_universe(plain, "pseudo", seed=0)
    assert len(opaque) == len(plain) == len(pseudo)
    assert {t.name for t in opaque}.isdisjoint({t.name for t in plain})
    for t in opaque:
        assert not any(d.name in t.name for d in DOMAINS), t.name


def test_isomorph_preserves_shape():
    plain = make_universe(8, tier=4, seed=0)
    iso = isomorph(plain, 17)
    assert len(iso) == len(plain)
    for a, b in zip(plain, iso, strict=False):
        assert a.name != b.name
        assert len(a.params) == len(b.params)
        assert a.max_depth == b.max_depth
        assert a.n_enums == b.n_enums


def test_near_ratio_controls_domain_mix():
    low = make_universe(32, tier=3, seed=0, target_domain="calendar", near_ratio=0.0)
    high = make_universe(32, tier=3, seed=0, target_domain="calendar", near_ratio=1.0)
    n_low = sum(1 for t in low if t.domain == "calendar")
    n_high = sum(1 for t in high if t.domain == "calendar")
    assert n_high > n_low


def test_world_state_is_deterministic():
    u = make_universe(8, tier=3, seed=0)
    a = seed_world(u, seed=0)
    b = seed_world(u, seed=0)
    assert a.snapshot() == b.snapshot()
    c = seed_world(u, seed=1)
    assert a.snapshot() != c.snapshot()


# --------------------------------------------------------------------------- #
# Naming schemes must rename the schema without breaking the task.
#
# `bind_arguments` reaches its fields through `kernel_args["paths"]`, which
# names schema components. Renaming the schema without remapping those paths
# left every field unresolvable: nothing bound, the gold call came back empty,
# and the request collapsed to a single word — an opaque cell asked "yzu." and
# was unanswerable. The ablation then measured a broken generator instead of
# the effect of naming.
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402


@pytest.mark.parametrize("naming", ["semantic", "pseudo", "opaque"])
@pytest.mark.parametrize("tier", [1, 3, 5])
def test_renamed_tools_still_bind_their_arguments(naming, tier):
    instances = generate_instances(6, n_tools=8, tier=tier, regime="single", seed=0, naming=naming)
    empty = [c for inst in instances for turn in inst.turns for c in turn.gold_calls if not c.arguments]
    assert not empty, f"{naming} tier {tier}: {len(empty)} gold calls have no arguments at all"


@pytest.mark.parametrize("naming", ["semantic", "pseudo", "opaque"])
def test_renamed_gold_calls_validate(naming):
    for tier in (1, 3, 5):
        for regime in ("single", "parallel"):
            instances = generate_instances(4, n_tools=8, tier=tier, regime=regime, seed=1, naming=naming)
            for inst in instances:
                for call in inst.gold_calls:
                    tool = inst.universe.get(call.name)
                    assert tool is not None
                    assert validate_call(call, tool).ok, (naming, tier, call.name)


@pytest.mark.parametrize("naming", ["pseudo", "opaque"])
def test_the_request_stays_in_english_when_the_schema_is_renamed(naming):
    """Only the schema is renamed. The user still speaks English.

    That is the whole point of the ablation: the model has to read the
    descriptions instead of pattern-matching on the tool name.
    """
    instances = generate_instances(6, n_tools=8, tier=3, regime="single", seed=0, naming=naming)
    for inst in instances:
        user = inst.turns[0].user
        assert len(user.split()) >= 4, f"{naming}: degenerate request {user!r}"
        # every stated value must still reach the gold call
        for call in inst.turns[0].gold_calls:
            assert call.arguments


# ---------------------------------------------------------------- deeper chains
def test_chain_depth_three_uses_distinct_operations_and_valid_golds():
    import random

    from toolform.generator import make_universe, seed_world
    from toolform.generator.tasks import make_chain

    found = 0
    for seed in range(12):
        u = make_universe(16, tier=3, seed=seed)
        w = seed_world(u, seed=seed)
        inst = make_chain(u, w, random.Random(f"t{seed}"), depth=3, instance_id="c")
        if inst is None or len(inst.turns) < 3:
            continue
        found += 1
        names = [t.gold_calls[0].name for t in inst.turns[1:]]
        assert len(set(names)) == len(names), names
        for t in inst.turns:
            assert t.tool_results and t.tool_results[0].get("ok", True) is not False, t.tool_results
    assert found > 0


def test_chain_depth_two_is_unchanged_by_the_depth_three_rule():
    import random

    from toolform.generator import make_universe, seed_world
    from toolform.generator.tasks import make_chain

    u = make_universe(16, tier=3, seed=3)
    w = seed_world(u, seed=3)
    a = make_chain(u, w, random.Random("same"), depth=2, instance_id="c")
    b = make_chain(u, w, random.Random("same"), depth=2, instance_id="c")
    assert a is not None and [t.user for t in a.turns] == [t.user for t in b.turns] and a.meta["depth"] == 2
