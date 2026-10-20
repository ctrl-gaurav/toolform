"""Naming schemes for generated tools.

Naming is its own experimental axis. A model can often guess the right tool
from the name alone without reading a single line of schema; stripping the
names is how we separate "reading the interface" from "pattern matching on
English".

Three schemes:

``semantic``
    Real words drawn from the domain (``calendar_schedule``, ``start_hour``).

``opaque``
    Deterministically scrambled identifiers with no lexical clue
    (``fn_qv7``, ``a3``). The schema is the only source of information.

``pseudo``
    Pronounceable but meaningless words (``varnek_delo``, ``polim``). Controls
    for the possibility that opaque names hurt merely because they look like
    noise rather than because they carry no meaning.

Isomorphic renaming (:func:`isomorph`) produces a fresh but structurally
identical copy of a universe. Comparing accuracy before and after is our
contamination check: a real drop means the original names were memorised.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import replace

from ..ir import ParamIR, ToolIR, ToolUniverse, TypeIR

_CONS = "bdfgklmnprstvz"
_VOWELS = "aeiou"


def _rng(seed: int | str) -> random.Random:
    if isinstance(seed, str):
        seed = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def pseudo_word(rng: random.Random, syllables: int = 2) -> str:
    out = []
    for _ in range(syllables):
        out.append(rng.choice(_CONS) + rng.choice(_VOWELS))
        if rng.random() < 0.4:
            out.append(rng.choice(_CONS))
    return "".join(out)


def opaque_token(rng: random.Random, n: int = 3) -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(rng.choice(alphabet) for _ in range(n))


def rename_universe(
    universe: ToolUniverse,
    scheme: str = "semantic",
    seed: int = 0,
) -> ToolUniverse:
    """Return a copy of ``universe`` with names rewritten under ``scheme``."""
    if scheme == "semantic":
        return universe

    rng = _rng(f"{scheme}:{seed}:{universe.universe_id}")
    used_tools: set[str] = set()
    tools: list[ToolIR] = []
    for i, t in enumerate(universe):
        new_name = _new_tool_name(scheme, rng, i, used_tools)
        used_tools.add(new_name)
        used_params: set[str] = set()
        params = tuple(_rename_param(p, scheme, rng, j, used_params) for j, p in enumerate(t.params))
        # The kernel reaches its fields through `kernel_args["paths"]`, which
        # names schema components. Renaming the schema without remapping those
        # paths left every field unresolvable: no argument bound, the gold call
        # came back empty, and `render_request` had nothing to say — so an
        # opaque cell asked "yzu." and was unanswerable. The naming ablation
        # then measured a broken generator rather than the effect of naming.
        tools.append(
            replace(
                t,
                name=new_name,
                params=params,
                kernel_args=_remap_kernel_args(t.kernel_args, t.params, params),
            )
        )
    return ToolUniverse(
        tools=tools,
        universe_id=f"{universe.universe_id}:{scheme}",
        seed=universe.seed,
        meta={**universe.meta, "naming": scheme},
    )


def _name_map(old_params, new_params) -> dict:
    """old param name -> (new param name, map for its nested fields).

    Renaming is positional, so old and new can be walked in lockstep.
    """
    out: dict = {}
    for op, np_ in zip(old_params, new_params, strict=False):
        nested = {}
        if op.type.fields and np_.type.fields:
            nested = _name_map(op.type.fields, np_.type.fields)
        out[op.name] = (np_.name, nested)
    return out


def _remap_kernel_args(kernel_args: dict, old_params, new_params) -> dict:
    """Point `paths` at the renamed schema, keeping the semantic field keys.

    The keys stay semantic on purpose: they drive the world state and the
    request text, which must keep saying "book a flight to Paris" even when the
    tool is called `fn_yzu`. Only the schema the model reads is renamed — that
    is exactly what the ablation is meant to test.
    """
    paths = kernel_args.get("paths")
    if not paths:
        return kernel_args
    mapping = _name_map(old_params, new_params)
    new_paths: dict = {}
    for field, path in paths.items():
        cur = mapping
        out = []
        for component in path:
            if component not in cur:
                out = []
                break
            new_component, cur = cur[component]
            out.append(new_component)
        if out:
            new_paths[field] = out
    return {**kernel_args, "paths": new_paths}


def _new_tool_name(scheme: str, rng: random.Random, i: int, used: set[str]) -> str:
    for _ in range(200):
        if scheme == "opaque":
            cand = f"fn_{opaque_token(rng)}"
        elif scheme == "pseudo":
            cand = f"{pseudo_word(rng)}_{pseudo_word(rng)}"
        else:
            raise ValueError(f"unknown naming scheme {scheme!r}")
        if cand not in used:
            return cand
    return f"fn_{i}"


def _rename_param(p: ParamIR, scheme: str, rng: random.Random, j: int, used: set[str]) -> ParamIR:
    for _ in range(200):
        if scheme == "opaque":
            cand = f"a{j}" if rng.random() < 0.5 else opaque_token(rng, 2)
        else:
            cand = pseudo_word(rng)
        if cand not in used:
            used.add(cand)
            return replace(p, name=cand, type=_rename_type(p.type, scheme, rng))
    return replace(p, name=f"a{j}")


def _rename_type(t: TypeIR, scheme: str, rng: random.Random) -> TypeIR:
    if not t.fields:
        return t
    used: set[str] = set()
    return replace(
        t,
        fields=tuple(_rename_param(f, scheme, rng, k, used) for k, f in enumerate(t.fields)),
    )


# --------------------------------------------------------------------------- #
# isomorphic renaming for contamination checks
# --------------------------------------------------------------------------- #

_SYNONYM_SEEDS = (
    "arc brim clove dune ember frost glade haven iris jute kiln lark moss nook "
    "opal pike quill rune sage tarn urn vane wisp yarn zeal"
).split()


ISOMORPH_LEVELS = ("names", "args", "descriptions", "all")

# Round two of the contamination check: the surface
# strings a model could have memorised beyond the tool name. Every level
# keeps the structure, the types, the gold calls (remapped positionally)
# and the request text, so the task stays answerable.
#   names         round one: tool and parameter names get a fresh head word,
#                 the parameter keeps its last word (`days_ahead` -> `lark_ahead`)
#   args          the parameter name is an opaque pseudo-word with no tail
#                 (`days_ahead` -> `lark_mopu`); its description is untouched,
#                 so the description is the only way to place a value
#   descriptions  names as in round one; every tool and parameter description
#                 re-worded by a fixed template (same meaning, other words)
#   all           args and descriptions together
_REWORD_TOOL = (
    "{body}",
    "Use this to {lower}",
    "Operation: {lower}",
    "{body} (this tool)",
    "Call it to {lower}",
    "What it does: {lower}",
)
_REWORD_PARAM = (
    "{body}",
    "The value for: {lower}",
    "Give {lower}",
    "Specifies {lower}",
    "{body} (an input)",
    "Input: {lower}",
)


def _reword(text: str, rng: random.Random, templates: tuple[str, ...]) -> str:
    """The same meaning in other words, deterministically.

    The first sentence is wrapped by a template; the sentences after it (a
    unit, a range, an enum note) are kept and shuffled. Nothing semantic is
    added or removed: a model that reads the description still finds every
    fact it held before, only never in the stock wording."""
    if not text:
        return text
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x.strip()]
    head, rest = parts[0], parts[1:]
    body = head.rstrip(".!?")
    lower = body[:1].lower() + body[1:] if body[:1].isupper() and not body[:2].isupper() else body
    tmpl = rng.choice(templates[1:]) if len(templates) > 1 else templates[0]
    head = tmpl.format(body=body, lower=lower).rstrip(".") + "."
    rng.shuffle(rest)
    return " ".join([head, *rest])


def isomorph(universe: ToolUniverse, seed: int, level: str = "names") -> ToolUniverse:
    """Structure-preserving rename with fresh but still word-like names.

    Used for the contamination replay: identical difficulty, different
    surface strings. A drop in accuracy on the isomorph means the original
    names were memorised rather than read. ``level`` picks how much of the
    surface is replaced (see ISOMORPH_LEVELS); the default is round one.
    """
    if level not in ISOMORPH_LEVELS:
        raise ValueError(f"unknown isomorph level {level!r}; one of {ISOMORPH_LEVELS}")
    rng = _rng(f"isomorph:{seed}:{universe.fingerprint()}")
    pool = list(_SYNONYM_SEEDS)
    rng.shuffle(pool)
    idx = 0
    # The rewording and the opaque tails draw from their own streams, so
    # the names of round one are the same under every level: a level only
    # adds to round one, never re-draws it.
    rng_words = _rng(f"isomorph-words:{seed}:{universe.fingerprint()}")
    rng_args = _rng(f"isomorph-args:{seed}:{universe.fingerprint()}")
    opaque_args = level in ("args", "all")
    reword = level in ("descriptions", "all")
    seen_tails: set[str] = set()

    def take() -> str:
        nonlocal idx
        w = pool[idx % len(pool)]
        idx += 1
        return w if idx <= len(pool) else f"{w}{idx // len(pool)}"

    def tail(p_name: str) -> str:
        if not opaque_args:
            return p_name.split("_")[-1]
        while True:
            t = pseudo_word(rng_args, syllables=2)
            if t not in seen_tails and t not in _SYNONYM_SEEDS:
                seen_tails.add(t)
                return t

    tools: list[ToolIR] = []
    for t in universe:
        verb = t.name.split("_")[-1]
        new_name = f"{take()}_{verb}"
        params = []
        for p in t.params:
            q = replace(p, name=f"{take()}_{tail(p.name)}")
            if reword:
                q = replace(q, description=_reword(q.description, rng_words, _REWORD_PARAM))
            params.append(q)
        desc = _reword(t.description, rng_words, _REWORD_TOOL) if reword else t.description
        tools.append(replace(t, name=new_name, params=tuple(params), description=desc))
    return ToolUniverse(
        tools=tools,
        universe_id=f"{universe.universe_id}:iso{seed}" + ("" if level == "names" else f"-{level}"),
        seed=universe.seed,
        meta={**universe.meta, "isomorph_of": universe.universe_id, "isomorph_seed": seed, "isomorph_level": level},
    )


def remap_calls(calls, universe_before: ToolUniverse, universe_after: ToolUniverse):
    """Translate gold calls from one naming to another, positionally."""
    from ..ir import ToolCall

    name_map = {a.name: b.name for a, b in zip(universe_before, universe_after, strict=False)}
    param_maps = {
        a.name: {pa.name: pb.name for pa, pb in zip(a.params, b.params, strict=False)}
        for a, b in zip(universe_before, universe_after, strict=False)
    }
    out = []
    for c in calls:
        new_name = name_map.get(c.name, c.name)
        pm = param_maps.get(c.name, {})
        out.append(
            ToolCall(
                name=new_name,
                arguments={pm.get(k, k): v for k, v in c.arguments.items()},
                call_id=c.call_id,
            )
        )
    return out
