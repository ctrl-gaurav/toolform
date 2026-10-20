"""A gold call must validate against its own schema and execute.

Generator v2 keeps this as an invariant. Generator v1 is reproduced as drawn and
the known gap is documented here,
not silently fixed: the test records how many v1 golds fail, and asserts zero
under v2.
"""

from toolform.generator.tasks import execute_gold, generate_instances
from toolform.generator.universe import seed_world
from toolform.ir import validate_call


def _failures(version: int, seeds=range(4), n_tools=32) -> tuple[int, int]:
    bad = total = 0
    for seed in seeds:
        for inst in generate_instances(
            20,
            n_tools=n_tools,
            tier=3,
            regime="single",
            seed=seed,
            naming="semantic",
            near_ratio=0.5,
            generator_version=version,
        ):
            world = seed_world(inst.universe, seed=inst.world_seed)
            for turn in inst.turns:
                for gold in turn.gold_calls:
                    total += 1
                    tool = inst.universe.get(gold.name)
                    ok = validate_call(gold, tool).ok
                    if ok:
                        ok = execute_gold(tool, gold, world.clone()).ok
                    bad += 0 if ok else 1
    return bad, total


def test_every_v2_gold_validates_and_executes():
    bad, total = _failures(2)
    assert total > 0 and bad == 0, (bad, total)


def test_v1_gold_gap_is_small_and_known():
    bad, total = _failures(1)
    # v1 is reproduced as drawn; the array-field gap is a few golds at most
    assert bad <= 0.05 * total, (bad, total)
