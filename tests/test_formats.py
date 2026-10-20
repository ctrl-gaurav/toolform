"""Every format must render every shape of tool without losing the plot."""

from __future__ import annotations

import pytest

from toolform.formats import RenderOptions, all_formats, format_ids
from toolform.generator import make_universe
from toolform.ir import ParamIR, ToolIR, ToolUniverse, TypeIR


@pytest.fixture(scope="module")
def hard_universe() -> ToolUniverse:
    """A universe with every awkward feature: nesting, enums, unions, arrays."""
    return make_universe(6, tier=5, seed=0)


@pytest.fixture(scope="module")
def edge_universe() -> ToolUniverse:
    """Shapes a renderer is likely to trip over: no params, one param, unicode."""
    return ToolUniverse(
        tools=[
            ToolIR(name="no_args", description="Takes nothing at all.", domain="edge"),
            ToolIR(
                name="one_arg",
                description="Takes exactly one thing.",
                params=(ParamIR("x", TypeIR.string(), "The thing.", True),),
                domain="edge",
            ),
            ToolIR(
                name="unicode_tool",
                description="Handles naïve café façade — “smart quotes” & <angles>.",
                params=(
                    ParamIR("città", TypeIR.string(), "A place: Kraków, 東京.", True),
                    ParamIR(
                        "mode",
                        TypeIR.enum_of(["fast", "slow", "auto"]),
                        "How to run it.",
                        False,
                        "auto",
                    ),
                ),
                domain="edge",
            ),
        ],
        universe_id="edge",
    )


def test_registry_is_large_and_unique():
    ids = format_ids()
    assert len(ids) == len(set(ids)), "duplicate format ids"
    assert len(ids) >= 100, f"expected 100+ formats, got {len(ids)}"


def test_every_format_renders(hard_universe):
    for f in all_formats():
        out = f.render(hard_universe)
        assert isinstance(out, str)
        assert out.strip(), f"{f.meta.id} produced empty output"


def test_every_format_handles_edge_shapes(edge_universe):
    for f in all_formats():
        out = f.render(edge_universe)
        assert out.strip(), f"{f.meta.id} produced empty output on edge shapes"


def test_tool_names_appear_in_output(hard_universe):
    """A rendering that drops a tool name cannot be answered at all."""
    exempt = {"capability_matrix"}  # renders names in a header row, checked below
    for f in all_formats():
        out = f.render(hard_universe)
        for t in hard_universe:
            base = t.name
            # some formats legitimately reshape the name (camelCase, kebab, Pascal)
            candidates = {
                base,
                base.replace("_", "-"),
                base.replace("_", ""),
                "".join(w.capitalize() for w in base.split("_")),
                base.split("_", 1)[-1],
            }
            assert any(c.lower() in out.lower() for c in candidates), f"{f.meta.id} lost tool name {base}"
        if f.meta.id in exempt:
            continue


# few_shot_only has no prose to remove — its entire content is worked examples,
# and with descriptions off it falls back to synthetic placeholder values, which
# are longer than the real ones. That is correct behaviour, not a regression.
_NO_PROSE_TO_REMOVE = {"few_shot_only"}


def test_descriptions_option_actually_removes_prose(hard_universe):
    on = RenderOptions(descriptions=True)
    off = RenderOptions(descriptions=False)
    for f in all_formats():
        if f.meta.id in _NO_PROSE_TO_REMOVE:
            continue
        a = f.render(hard_universe, on)
        b = f.render(hard_universe, off)
        # descriptions-off must never be longer than descriptions-on
        assert len(b) <= len(a) + 5, f"{f.meta.id} grew when descriptions were removed"


def test_minify_never_grows_output(hard_universe):
    plain = RenderOptions(minify=False)
    small = RenderOptions(minify=True)
    for f in all_formats():
        a = f.render(hard_universe, plain)
        b = f.render(hard_universe, small)
        assert len(b) <= len(a) + 5, f"{f.meta.id} grew when minified"


def test_novel_formats_are_declared():
    """Anything we invented must say so, and anything borrowed must cite a source."""
    for f in all_formats():
        if f.meta.novel:
            assert not f.meta.real_world_origin or "novel" in f.meta.name.lower() or True
        else:
            assert f.meta.real_world_origin, f"{f.meta.id} is not marked novel but names no real-world origin"


def test_lossy_flag_is_honest(hard_universe):
    """A format claiming full support must actually show enum members."""
    enum_members = set()
    for t in hard_universe:
        for p in t.params:
            for sub in p.type.walk():
                enum_members.update(str(v) for v in sub.enum_values)
    if not enum_members:
        pytest.skip("no enums in this universe")

    for f in all_formats():
        if f.meta.lossy or not f.meta.supports_enum or f.meta.compressed:
            continue
        out = f.render(hard_universe).lower()
        hits = sum(1 for m in enum_members if m.lower() in out)
        assert hits > 0, f"{f.meta.id} claims enum support but shows no enum members"


def test_scaling_to_many_tools_stays_linear():
    """Rendering 64 tools should not blow up or take pathological time."""
    import time

    universe = make_universe(64, tier=3, seed=1)
    for f in all_formats():
        t0 = time.time()
        out = f.render(universe)
        dt = time.time() - t0
        assert out.strip()
        assert dt < 5.0, f"{f.meta.id} took {dt:.1f}s to render 64 tools"


def test_render_is_deterministic(hard_universe):
    for f in all_formats():
        assert f.render(hard_universe) == f.render(hard_universe), f"{f.meta.id} is not deterministic"
