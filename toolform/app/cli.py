"""The ``toolform`` command line.

Every command takes ``--json`` (the result's ``to_dict()`` and nothing else)
and ``--help``. Exit codes: 0 success, 1 a check failed (``guard --fail-on``,
``parse`` on a bad reply, ``doctor``), 2 a usage error, 3 an input error
(unreadable tools, unknown format or protocol), 4 an endpoint error.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, TypeVar

import typer

from ..sdk.constants import (
    CORE_FORMATS,
    DEFAULT_PORT,
    FRAMEWORK_VERSION,
    STUDY_FORMAT_COUNT,
    STUDY_PROTOCOL_COUNT,
    TWO_STAGE_FORMATS,
)
from ..sdk.errors import ClientError, ToolFormError
from .output import console, dumps, emit, error, escape, pct, say, table, warn

EPILOG = "Documentation: https://ctrl-gaurav.github.io/toolform/docs/"

app = typer.Typer(
    name="toolform",
    help=(
        "ToolForm: tool interfaces, chosen by measurement. Recommend, render, parse and guard the tool "
        "interface of an LLM agent, from a study of 129 formats, 31 answer protocols and 112 models."
    ),
    epilog=EPILOG,
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback()
def _root(
    debug: bool = typer.Option(
        False, "--debug", help="Show the full traceback of an error (the same as TOOLFORM_DEBUG=1)."
    ),
) -> None:
    # The app's own help text stays; this callback only reads the global --debug flag.
    if debug:
        os.environ["TOOLFORM_DEBUG"] = "1"


PANEL_CHOOSE = "Choose"
PANEL_BUILD = "Build and run"
PANEL_PROTECT = "Protect and scale"
PANEL_OPERATE = "Operate"

F = TypeVar("F", bound=Callable[..., Any])


# --------------------------------------------------------------------------- #
# choices
# --------------------------------------------------------------------------- #


class Kind(str, Enum):
    auto = "auto"
    openai = "openai"
    anthropic = "anthropic"
    mcp = "mcp"
    ir = "ir"
    python = "python"
    typescript = "typescript"


class Rule(str, Enum):
    main = "main"
    symmetric = "symmetric"
    as_written = "as_written"


class Objective(str, Enum):
    accuracy = "accuracy"
    cost = "cost"


class PriceName(str, Enum):
    frontier_api = "frontier_api"
    self_hosted = "self_hosted"


class Strictness(str, Enum):
    lenient = "lenient"
    standard = "standard"
    strict = "strict"


class GuardAction(str, Enum):
    report = "report"
    # Named strip_ because a member called "strip" would shadow str.strip on every member.
    strip_ = "strip"
    drop_descriptions = "drop-descriptions"


class StripAt(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Scope(str, Enum):
    flagged = "flagged"
    all = "all"


class FailOn(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    never = "never"


class Case(str, Enum):
    as_is = "as_is"
    snake = "snake"
    camel = "camel"
    pascal = "pascal"
    kebab = "kebab"
    screaming = "screaming"


class Persona(str, Enum):
    agent = "agent"
    terse = "terse"
    bare = "bare"
    expert = "expert"


class ExportTo(str, Enum):
    openai = "openai"
    anthropic = "anthropic"
    mcp = "mcp"
    ir = "ir"


JSON_OPT = typer.Option(False, "--json", help="Print the result as JSON and nothing else.")
FROM_OPT = typer.Option(Kind.auto, "--from", help="What kind of tool file it is; auto detects it.")
TOOLS_ARG = typer.Argument(
    ...,
    metavar="TOOLS",
    help="A tool file (OpenAI, Anthropic, MCP or IR JSON, a .py "
    "or a .ts file), or - for stdin. A .py file is imported, "
    "which runs its code.",
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _message(exc: BaseException) -> str:
    if isinstance(exc, KeyError) and not isinstance(exc, ToolFormError):
        return str(exc.args[0]) if exc.args else "missing key"
    return str(exc)


def _debug() -> bool:
    return os.environ.get("TOOLFORM_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def handle_errors(fn: F) -> F:
    """Turn the framework's errors into a one-line message and the documented exit code.

    With ``--debug`` or ``TOOLFORM_DEBUG=1`` the error is raised with its traceback instead.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except Exception as exc:
            if _debug():
                raise
            # Usage errors (typer.BadParameter and its kin) keep their own exit code 2. Recent typer
            # releases no longer install click, so they are recognised by shape, not by import.
            if hasattr(exc, "exit_code") and hasattr(exc, "show"):
                raise
            if not isinstance(exc, (ClientError, ToolFormError, ValueError, KeyError, OSError)):
                raise
            _raise_exit(exc)

    return wrapper  # type: ignore[return-value]


def _raise_exit(exc: Exception) -> None:
    """Print the error in one line and exit 4 for an endpoint, 3 for any other input error."""
    error(_message(exc))
    raise typer.Exit(4 if isinstance(exc, ClientError) else 3) from exc


def _split(csv: str | None) -> list[str] | None:
    if csv is None:
        return None
    items = [x.strip() for x in csv.split(",") if x.strip()]
    return items or None


def _write(path: str, text: str) -> None:
    p = Path(path).expanduser()
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _facts() -> dict[str, float]:
    from ..advisor.evidence import load_evidence

    return {f["id"]: f["value"] for f in load_evidence().facts()}


def _load(tools: str, source: Kind) -> Any:
    from .inputs import read_tools

    return read_tools(tools, kind=source.value)


# --------------------------------------------------------------------------- #
# recommend
# --------------------------------------------------------------------------- #

_MATCHED = {
    "zoo": "matched in the model zoo",
    "pattern": "matched by a name pattern",
    "anchor": "an anchor model of the study",
    "family": "family given",
    "none": "not matched",
    "checkpoint": "a checkpoint of the study, with its own row",
}


def _render_recommendation(rec: Any) -> None:
    d = rec.to_dict()
    res = d["resolution"]
    s = d["situation"]
    out = console()
    who = s.get("model") or s.get("family") or "an unnamed model"
    out.print(f"ToolForm recommendation for {escape(str(who))}", style="bold")
    if res["anchor"]:
        model_line = f"anchor {res['anchor']}, {_MATCHED['anchor']}"
    elif res.get("checkpoint") and d["basis"].startswith("checkpoint:"):
        model_line = f"checkpoint {res['checkpoint']} (family {res['family']}), {_MATCHED['checkpoint']}"
    elif res["family"]:
        label = f" ({res['family_label']})" if res.get("family_label") else ""
        model_line = f"family {res['family']}{label}, {_MATCHED.get(res['matched_by'], res['matched_by'])}"
    else:
        model_line = "not matched to a family; the advisor uses the pooled tables"
    tokens = d["schema_tokens"]
    tok_src = {"study": "study, tab_cost", "rendered": "rendered, characters / 4"}.get(
        d["tokens_source"], d["tokens_source"]
    )
    rows = [
        ("model", model_line, ""),
        ("format", d["format_id"], d["format_name"]),
        ("protocol", d["protocol_id"], d["protocol_name"]),
        (
            "expected",
            pct(d["expected_accuracy"]),
            f"range {d['interval'][0]:.2f} to {d['interval'][1]:.2f} across the table values it rests on",
        ),
        (
            "tokens",
            f"about {tokens:,}" if tokens is not None else "unknown",
            f"schema tokens for {s['n_tools']} tools ({tok_src})",
        ),
        (
            "catalogue",
            d["catalogue"]["strategy"],
            f"{s['n_tools']} tools, tier {s['tier']}"
            + (f", context {d['context_tokens']:,} tokens" if d.get("context_tokens") else ""),
        ),
        (
            "rule",
            d["rule"],
            {
                "main": "the parser each protocol ships with",
                "symmetric": "the same re-nesting repair under every protocol",
                "as_written": "no repair",
            }.get(d["rule"], ""),
        ),
        (
            "basis",
            d["basis"],
            f"evidence {d['evidence_version']}" + (f"; {rec._basis_note}" if getattr(rec, "_basis_note", "") else ""),
        ),
    ]
    for k, v, note in rows:
        out.print(f"  {k:<10} {escape(str(v)):<18} {escape(note)}")
    if d["tied_with"]:
        out.print(f"  tied with  {escape(', '.join(d['tied_with']))} (within 2 points)")
    alts = d["alternatives"][:7]
    if alts:
        out.print()
        table(
            [
                {
                    "candidate": f"{a['format_id']} + {a['protocol_id']}",
                    "expected": pct(a["expected_accuracy"]),
                    "tokens": "" if a["schema_tokens"] is None else f"{a['schema_tokens']:,}",
                }
                for a in alts
            ],
            ["candidate", "expected", "tokens"],
            headers=["Alternatives", "expected", "tokens"],
        )
    out.print()
    out.print("Why", style="bold")
    out.print(escape(d["explanation"]))
    if d["catalogue"]["strategy"] != "one_shot":
        out.print()
        out.print("Catalogue", style="bold")
        out.print(escape(d["catalogue"]["reason"]))
    if d["guard"]:
        out.print()
        out.print("Guard", style="bold")
        out.print(escape(f"{d['guard']['action']}: {d['guard']['reason']}"))
    if d["surface"]:
        sf = d["surface"]
        out.print()
        out.print(
            escape(
                f"Fitted surface (extrapolation only, held-out R2 {sf.get('heldout_r2')}): "
                f"{sf.get('predicted_accuracy')}% for {sf.get('format_id')} at {sf.get('params_b')}B."
            )
        )
    if d["warnings"]:
        out.print()
        out.print("Warnings", style="bold")
        for w in d["warnings"]:
            out.print(escape(f"- {w}"))
    out.print()
    model = s.get("model") or "MODEL"
    flag = " --no-thinking" if "--no-thinking" in d["measure_hint"] else ""
    out.print(escape(f"Measure it: toolform ab-test --base-url http://localhost:8000/v1 --model {model}{flag}"))
    out.print(escape(d["measure_hint"]))
    out.print(
        escape(
            "The advisor combines the study's per-factor tables; the combination itself was not "
            "evaluated, which is why measuring on the model is the stronger evidence."
        ),
        style="dim",
    )


@app.command("recommend", rich_help_panel=PANEL_CHOOSE)
@handle_errors
def recommend_cmd(
    model: Optional[str] = typer.Option(None, "--model", help="A model id or name, for example Qwen/Qwen3-8B."),
    family: Optional[str] = typer.Option(None, "--family", help="A model-zoo family key, for example qwen3."),
    params_b: Optional[float] = typer.Option(None, "--params-b", help="Parameters in billions."),
    tools_file: Optional[str] = typer.Option(
        None, "--tools-file", help="Take the tool count, tier and tokens from these tools."
    ),
    source: Kind = FROM_OPT,
    n_tools: Optional[int] = typer.Option(
        None, "--n-tools", min=1, help="Tools shown at once (default 8, or the file's count)."
    ),
    tier: Optional[int] = typer.Option(
        None, "--tier", min=1, help="Complexity tier 1 to 5 (default 3, or the file's)."
    ),
    budget: Optional[int] = typer.Option(None, "--budget", min=1, help="Most tokens the tool block may take."),
    context: Optional[int] = typer.Option(None, "--context", min=1, help="The model's context window."),
    objective: Objective = typer.Option(Objective.accuracy, "--objective"),
    price: PriceName = typer.Option(PriceName.frontier_api, "--price", help="Price vector for the cost objective."),
    rule: Rule = typer.Option(Rule.main, "--rule", help="Grading rule the expected accuracy is read under."),
    protocol: Optional[str] = typer.Option(None, "--protocol", help="Fix the answer protocol."),
    candidates: Optional[str] = typer.Option(None, "--candidates", help="Comma-separated format ids to rank."),
    third_party: bool = typer.Option(False, "--third-party", help="The tools come from someone else."),
    as_json: bool = JSON_OPT,
) -> None:
    """Recommend a schema format and answer protocol from the study's evidence."""
    from ..advisor import Situation, recommend

    ts = _load(tools_file, source) if tools_file else None
    if ts is not None and len(ts) == 0:
        raise ValueError(f"{tools_file} holds no tools; give at least one")
    n = n_tools if n_tools is not None else (len(ts) if ts is not None else 8)
    t = tier if tier is not None else (ts.tier_estimate() if ts is not None else 3)
    cands = _split(candidates)
    situation = Situation.from_dict(
        {
            "model": model,
            "family": family,
            "params_b": params_b,
            "n_tools": n,
            "tier": t,
            "token_budget": budget,
            "context_tokens": context,
            "objective": objective.value,
            "price": price.value,
            "rule": rule.value,
            "protocol": protocol,
            "candidates": cands,
            "third_party_tools": third_party,
        }
    )
    rec = recommend(situation, tools=ts)
    emit(rec, as_json=as_json, render=_render_recommendation)


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #


def _study_accuracy(row: dict[str, Any]) -> str:
    if row.get("error"):
        return "render failed"
    if row.get("study_accuracy") is None:
        return "not measured"
    return f"{row['study_accuracy']:.2f}%"


@app.command("render", rich_help_panel=PANEL_BUILD)
@handle_errors
def render_cmd(
    tools: str = TOOLS_ARG,
    source: Kind = FROM_OPT,
    format_id: Optional[str] = typer.Option(None, "--format", help="A format id, for example xml_schema."),
    protocol: Optional[str] = typer.Option(None, "--protocol", help="A protocol id; default the format's own."),
    request: Optional[str] = typer.Option(None, "--request", help="A user request, for --messages."),
    descriptions: bool = typer.Option(True, "--descriptions/--no-descriptions"),
    constraints: bool = typer.Option(True, "--constraints/--no-constraints"),
    defaults: bool = typer.Option(True, "--defaults/--no-defaults"),
    returns: bool = typer.Option(True, "--returns/--no-returns"),
    minify: bool = typer.Option(False, "--minify"),
    case: Case = typer.Option(Case.as_is, "--case", help="Naming convention for names."),
    persona: Persona = typer.Option(Persona.agent, "--persona"),
    trust_line: bool = typer.Option(
        False,
        "--trust-line",
        help="Add the study's sentence calling tool metadata untrusted; it did not lower injection following.",
    ),
    null_clause: bool = typer.Option(True, "--null-clause/--no-null-clause"),
    messages: bool = typer.Option(False, "--messages", help="Print the full chat messages as JSON (needs --request)."),
    compare: bool = typer.Option(False, "--compare", help="Compare the size of every study format."),
    formats: Optional[str] = typer.Option(None, "--formats", help="Comma-separated format ids for --compare."),
    out: Optional[str] = typer.Option(None, "--out", help="Also write the output to this file."),
    as_json: bool = JSON_OPT,
) -> None:
    """Render tools in a format, with the answer instruction of a protocol."""
    from ..sdk.rendering import compare_formats, render, render_options

    ts = _load(tools, source)
    opts = render_options(
        descriptions=descriptions,
        constraints=constraints,
        defaults=defaults,
        returns=returns,
        minify=minify,
        case_convention=case.value,
    )
    if compare:
        rows = compare_formats(ts, _split(formats), options=opts)
        result = {"rows": rows}
        if out:
            _write(out, dumps(result))

        def show(_: Any) -> None:
            table(
                [
                    {
                        "format": r["format_id"] + ("  (novel)" if r["novel"] else ""),
                        "family": r["family"],
                        "tokens": "" if r["tokens_estimate"] is None else f"{r['tokens_estimate']:,}",
                        "study accuracy": _study_accuracy(r),
                        "paper tab_main": "" if r.get("paper_accuracy") is None else f"{r['paper_accuracy']:.2f}%",
                    }
                    for r in rows
                ],
                ["format", "family", "tokens", "study accuracy", "paper tab_main"],
            )
            say(
                f"{len(rows)} formats; tokens are characters / 4. (novel) marks a format the study introduced. "
                f"Study accuracy is each format's mean over every cell it ran in (the site export), one basis for "
                f"all formats. The paper's main-grid figure for the eight core formats is on other cells; do not "
                f"compare the two columns."
            )

        emit(result, as_json=as_json, render=show)
        return
    if not format_id:
        raise typer.BadParameter("give --format ID, or --compare", param_hint="--format")
    if messages and request is None:
        raise typer.BadParameter("--messages needs --request", param_hint="--messages")
    rp = render(
        ts,
        format_id,
        protocol,
        options=opts,
        request=request,
        persona=persona.value,
        null_clause=null_clause,
        trust_line=trust_line,
    )
    footer = f"{rp.format_id}: {rp.chars:,} chars, about {rp.tokens_estimate:,} tokens (characters / 4)"
    if messages:
        text = json.dumps(rp.messages, indent=2, ensure_ascii=False)
    else:
        text = f"{rp.tool_block}\n\n{rp.instructions}"
    if out:
        _write(out, dumps(rp) if as_json else text)

    def show_rendered(_: Any) -> None:
        sys.stdout.write(text + "\n")
        if not messages:
            say()
            say(footer, style="dim")
        sys.stdout.flush()

    emit(rp, as_json=as_json, render=show_rendered)


# --------------------------------------------------------------------------- #
# parse
# --------------------------------------------------------------------------- #


def validation_problems(v: dict[str, Any]) -> list[str]:
    """Plain lines for what a ``ValidationReport.to_dict()`` found wrong."""
    out: list[str] = []
    if v.get("unknown_tool"):
        out.append("unknown tool")
    for key, label in (
        ("missing_required", "missing required argument"),
        ("unknown_args", "unknown argument"),
        ("type_errors", "wrong type"),
        ("enum_errors", "not an allowed value"),
        ("constraint_errors", "breaks a constraint"),
    ):
        for item in v.get(key) or []:
            out.append(f"{label}: {item}")
    return out


@app.command("parse", rich_help_panel=PANEL_BUILD)
@handle_errors
def parse_cmd(
    tools: str = TOOLS_ARG,
    source: Kind = FROM_OPT,
    protocol: str = typer.Option(..., "--protocol", help="The protocol the prompt asked for, e.g. xml_call."),
    rule: Rule = typer.Option(Rule.main, "--rule"),
    text: Optional[str] = typer.Option(None, "--text", help="The reply text."),
    reply_file: Optional[str] = typer.Option(None, "--reply-file", help="A file holding the reply, or -."),
    lenient_fallback: bool = typer.Option(
        False, "--lenient-fallback", help="Take calls from any syntax when the strict parser finds none."
    ),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Check arguments against the schema."),
    require_call: bool = typer.Option(
        False, "--require-call", help="Exit 1 when the reply holds no accepted call, even if it says no tool applies."
    ),
    as_json: bool = JSON_OPT,
) -> None:
    """Parse a model's reply under a protocol and a grading rule; exit 1 when it is not ok.

    Not ok: a call was rejected, a tool name was invented, a call failed validation, or there is no call
    and the reply does not say that no tool applies. With --require-call, a reply with no call fails too.
    """
    from ..sdk.parse import parse_reply
    from .inputs import read_text

    if text is not None and reply_file is not None:
        raise typer.BadParameter("give --text or --reply-file, not both", param_hint="--text")
    ts = _load(tools, source)
    reply = read_text(text, reply_file)
    parsed = parse_reply(reply, ts, protocol, rule=rule.value, validate=validate, lenient_fallback=lenient_fallback)

    def show(p: Any) -> None:
        out = console()
        for c in p.calls:
            status = "valid" if c.valid else "invalid"
            args = json.dumps(c.arguments, ensure_ascii=False)
            out.print(escape(f"{c.resolved_name or c.name}  {status}  {args}"), style=None if c.valid else "yellow")
            if not c.valid:
                for e in validation_problems(c.validation):
                    out.print(escape(f"    {e}"), style="yellow")
            if c.repairs:
                out.print(escape(f"    repairs: {', '.join(c.repairs)}"), style="dim")
        for c in p.rejected:
            out.print(escape(f"{c.name}  rejected  {c.reason}"), style="red")
        if not p.calls and not p.rejected:
            out.print("no call" + (" (the reply says no tool applies)" if p.no_call_declared else ""))
        if p.note:
            out.print(escape(f"note: {p.note}"), style="dim")
        yes = {True: "yes", False: "no"}
        out.print(
            f"strict parse: {yes[p.parsed_strict]}, format compliant: {yes[p.format_compliant]}, "
            f"rule: {p.rule}, ok: {yes[p.ok]}"
        )

    emit(parsed, as_json=as_json, render=show)
    if not parsed.ok or (require_call and not parsed.calls):
        raise typer.Exit(1)


# --------------------------------------------------------------------------- #
# guard
# --------------------------------------------------------------------------- #

_SEV_RANK = {"high": 0, "medium": 1, "low": 2}


@app.command("guard", rich_help_panel=PANEL_PROTECT)
@handle_errors
def guard_cmd(
    tools: str = TOOLS_ARG,
    source: Kind = FROM_OPT,
    strictness: Strictness = typer.Option(
        Strictness.standard, "--strictness", help="lenient: high findings; standard: high and medium; strict: all."
    ),
    action: GuardAction = typer.Option(
        GuardAction.report,
        "--action",
        help="report (default) changes nothing; strip removes flagged sentences; drop-descriptions removes all prose.",
    ),
    strip_at: StripAt = typer.Option(
        StripAt.high, "--strip-at", help="With strip: remove findings at this severity or above (default high)."
    ),
    scope: Scope = typer.Option(Scope.flagged, "--scope", help="For drop-descriptions: flagged tools or all."),
    out: Optional[str] = typer.Option(None, "--out", help="Write the cleaned tools here, in the input's shape."),
    fail_on: FailOn = typer.Option(FailOn.high, "--fail-on", help="Exit 1 when a finding is at or above this."),
    trust_code: bool = typer.Option(
        False,
        "--trust-code",
        help="Allow a .py tools file. Loading it imports it, "
        "which runs its code; off by default here, since "
        "the guard is for tools you do not trust.",
    ),
    as_json: bool = JSON_OPT,
) -> None:
    """Flag or strip instructions hidden in tool descriptions (a heuristic, for CI over third-party tools)."""
    from ..guard import guard
    from .inputs import export_like_input, read_tools

    ts = read_tools(tools, kind=source.value, allow_python=trust_code)
    report = guard(
        ts,
        strictness=strictness.value,
        action=action.value.replace("-", "_"),
        scope=scope.value,
        strip_at=strip_at.value,
    )
    written = None
    if out and report.toolset is not None:
        exported = export_like_input(report.toolset)
        _write(out, json.dumps(exported["payload"], indent=2, ensure_ascii=False))
        written = (out, exported["kind"])

    def show(r: Any) -> None:
        o = console()
        by_tool: dict[str, list[Any]] = {}
        for f in r.findings:
            by_tool.setdefault(f.tool, []).append(f)
        for name, fs in by_tool.items():
            o.print(escape(name), style="bold")
            for f in fs:
                style = {"high": "red", "medium": "yellow"}.get(f.severity)
                o.print(escape(f"  {f.severity:<6} {f.rule_id}  {f.field}  {f.text!r}"), style=style)
        c = r.counts
        o.print(
            f"{r.n_tools} tools scanned, {len(r.flagged_tools)} flagged: {c.get('high', 0)} high, "
            f"{c.get('medium', 0)} medium, {c.get('low', 0)} low"
        )
        n = len(r.removed)
        if r.action == "strip":
            verb = "Stripped" if written else "Would strip"
            o.print(f"{verb} {n} span{'s' if n != 1 else ''} at {r.strip_at} severity or above.")
        elif r.action == "drop_descriptions":
            verb = "Removed" if written else "Would remove"
            o.print(f"{verb} {n} description field{'s' if n != 1 else ''}.")
        for k in r.kept:
            o.print(escape(f"Kept {k['tool']} {k['field']} {k['text']!r}: {k['reason']}."), style="yellow")
        if written:
            o.print(escape(f"Wrote the cleaned tools to {written[0]} ({written[1]} JSON)."))
        elif r.action != "report":
            o.print("Nothing was written; pass --out PATH to write the cleaned tools.")
        f = _facts()
        o.print(
            escape(
                f"In the study, a hidden instruction was followed on {f['injection_min']:.2f} to "
                f"{f['injection_max']:.2f}% of turns in every format that shows a description; a trust "
                f"sentence in the system prompt did not lower that. This guard is a heuristic; on a "
                f"held-out set of 50 descriptions it flagged 12 of 25 injected ones and 1 of 25 benign "
                f"ones at high severity."
            ),
            style="dim",
        )

    emit(report, as_json=as_json, render=show)
    if fail_on != FailOn.never and report.findings:
        worst = min(_SEV_RANK.get(f.severity, 9) for f in report.findings)
        if worst <= _SEV_RANK[fail_on.value]:
            raise typer.Exit(1)


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #


@app.command("catalogue", rich_help_panel=PANEL_PROTECT)
@handle_errors
def catalogue_cmd(
    tools: str = TOOLS_ARG,
    source: Kind = FROM_OPT,
    format_id: str = typer.Option("xml_schema", "--format", help="The format the block is rendered in."),
    context: Optional[int] = typer.Option(None, "--context", min=1, help="The model's context window."),
    budget: Optional[int] = typer.Option(None, "--budget", min=1, help="Most tokens the tool block may take."),
    query: Optional[str] = typer.Option(None, "--query", help="A request, to rank the tools against."),
    k: int = typer.Option(8, "--k", min=1, help="Tools to keep when retrieving."),
    fit: bool = typer.Option(False, "--fit", help="Shrink the tools to fit --budget."),
    out: Optional[str] = typer.Option(None, "--out", help="With --fit, write the reduced tools here."),
    as_json: bool = JSON_OPT,
) -> None:
    """Plan one-shot, retrieval or names-first disclosure for a long tool list."""
    from ..catalogue import fit_to_budget, plan_catalogue, retrieve
    from .inputs import export_like_input

    if fit and budget is None:
        raise typer.BadParameter("--fit needs --budget", param_hint="--fit")
    ts = _load(tools, source)
    plan = plan_catalogue(ts, format_id=format_id, context_tokens=context, budget_tokens=budget, query=query, k=k)
    result = plan.to_dict()
    ranking = None
    if query and plan.retrieval is None:
        ranking = retrieve(ts, query, k=k)
        result["ranking"] = ranking.to_dict()
    fitted = None
    if fit and budget is not None:
        fitted = fit_to_budget(ts, format_id, budget, query=query)
        result["fit"] = fitted.to_dict()
        if out:
            exported = export_like_input(fitted.toolset)
            _write(out, json.dumps(exported["payload"], indent=2, ensure_ascii=False))

    def show(_: Any) -> None:
        o = console()
        o.print(f"plan       {plan.strategy}", style="bold")
        o.print(f"tools      {plan.n_tools}")
        o.print(f"tokens     about {plan.schema_tokens:,} in {escape(plan.format_id)} (characters / 4)")
        if plan.context_tokens:
            o.print(f"context    {plan.context_tokens:,}")
        o.print()
        o.print(escape(plan.reason))
        if plan.evidence:
            o.print()
            table(
                [
                    {
                        "source": e.source,
                        "label": e.label,
                        "value": "" if e.value is None else f"{e.value:.2f}{e.unit}" if e.unit == "%" else str(e.value),
                        "interval": "" if not e.interval else f"[{e.interval[0]:.2f}, {e.interval[1]:.2f}]",
                    }
                    for e in plan.evidence
                ],
                ["source", "label", "value", "interval"],
                title="Evidence",
            )
        r = plan.retrieval or ranking
        if r is not None:
            o.print()
            table(
                [
                    {"rank": i + 1, "tool": n, "score": f"{s:.3f}", "kept": "yes" if n in r.toolset else ""}
                    for i, (n, s) in enumerate(r.ranked[: max(k, 10)])
                ],
                ["rank", "tool", "score", "kept"],
                title=f"BM25 ranking for {query!r}",
            )
        if plan.selection_messages:
            o.print()
            o.print(
                "The stage-one prompt names every tool and asks the model to pick one; "
                "run it with toolform.catalogue.TwoStage."
            )
        if fitted is not None:
            o.print()
            o.print(
                f"fit        {'fits' if fitted.fits else 'still over the budget'}: about "
                f"{fitted.tokens_before:,} -> {fitted.tokens_after:,} tokens, budget {fitted.budget_tokens:,}"
            )
            for d in fitted.dropped:
                what = d["tool"] + (f".{d['param']}" if d.get("param") else "")
                o.print(escape(f"  dropped {what}: {d['reason']} ({d.get('tokens', 0):,} tokens)"))
            if out:
                o.print(escape(f"Wrote {len(fitted.toolset)} tools to {out}."))

    emit(result, as_json=as_json, render=show)


# --------------------------------------------------------------------------- #
# convert
# --------------------------------------------------------------------------- #


@app.command("convert", rich_help_panel=PANEL_BUILD)
@handle_errors
def convert_cmd(
    tools: str = TOOLS_ARG,
    source: Kind = FROM_OPT,
    to: ExportTo = typer.Option(..., "--to", help="The shape to write."),
    out: Optional[str] = typer.Option(None, "--out", help="Write here instead of stdout."),
    as_json: bool = typer.Option(False, "--json", help="Accepted for symmetry; the output is always JSON."),
) -> None:
    """Load tools and write them as OpenAI, Anthropic, MCP or IR JSON."""
    from .inputs import export_tools

    ts = _load(tools, source)
    text = json.dumps(export_tools(ts, to.value), indent=2, ensure_ascii=False)
    if out:
        _write(out, text)
        if not as_json:
            warn(f"wrote {len(ts)} tools to {out} as {to.value}")
        return
    sys.stdout.write(text + "\n")


# --------------------------------------------------------------------------- #
# call
# --------------------------------------------------------------------------- #


@app.command("call", rich_help_panel=PANEL_BUILD)
@handle_errors
def call_cmd(
    tools: str = TOOLS_ARG,
    source: Kind = FROM_OPT,
    request: str = typer.Option(..., "--request", help="The user request."),
    base_url: Optional[str] = typer.Option(
        None, "--base-url", help="An OpenAI-compatible base URL, for example http://localhost:8000/v1."
    ),
    model: str = typer.Option(..., "--model", help="The model name the endpoint serves."),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="The variable holding the API key."),
    format_id: Optional[str] = typer.Option(None, "--format", help="Default: the advisor's choice for the model."),
    protocol: Optional[str] = typer.Option(None, "--protocol"),
    rule: Rule = typer.Option(Rule.main, "--rule"),
    guard: Optional[Strictness] = typer.Option(None, "--guard", help="Strip flagged description sentences first."),
    max_steps: int = typer.Option(8, "--max-steps", min=1),
    thinking: Optional[bool] = typer.Option(
        None,
        "--thinking/--no-thinking",
        help="Qwen 3 and 3.5 chat template switch (vLLM). Default: off for "
        "those families, as in the study; not sent otherwise.",
    ),
    anthropic: bool = typer.Option(False, "--anthropic", help="Use the Anthropic Messages API."),
    execute: bool = typer.Option(False, "--execute", help="Run the tools (a Python tools file)."),
    max_tokens: int = typer.Option(1024, "--max-tokens", min=1),
    as_json: bool = JSON_OPT,
) -> None:
    """Run the call loop against a model endpoint; without --execute it is a dry run."""
    from ..sdk.client import AnthropicClient, OpenAICompatClient
    from ..sdk.loop import CallLoop

    ts = _load(tools, source)
    if anthropic:
        kw: dict[str, Any] = {"api_key_env": api_key_env or "ANTHROPIC_API_KEY"}
        if base_url:
            kw["base_url"] = base_url
        client: Any = AnthropicClient(model, **kw)
    else:
        if not base_url:
            raise typer.BadParameter("give --base-url (or --anthropic)", param_hint="--base-url")
        client = OpenAICompatClient(
            base_url,
            model,
            api_key_env=api_key_env or "OPENAI_API_KEY",
            enable_thinking=_thinking_default(model, thinking),
        )
    if execute and not ts.executors:
        warn("these tools carry no executors (only a Python tools file does); this is a dry run")
    loop = CallLoop(
        client,
        ts,
        format_id=format_id,
        protocol_id=protocol,
        rule=rule.value,
        executors=None if execute else {},
        max_steps=max_steps,
        guard=guard.value if guard is not None else None,
        max_tokens=max_tokens,
    )
    first = loop.messages_for(request)
    result = loop.run(request)

    def show(r: Any) -> None:
        from ..sdk.tokens import estimate_tokens

        o = console()
        size = estimate_tokens("\n".join(m.get("content") or "" for m in first))
        o.print(
            escape(
                f"format {r.format_id} + {r.protocol_id}, rule {r.rule}; the first prompt is about "
                f"{size:,} tokens (characters / 4)"
            )
        )
        if loop.recommendation is not None:
            o.print(escape(f"chosen by the advisor: {loop.recommendation.summary()}"), style="dim")
        if loop.guard_report is not None and loop.guard_report.removed:
            o.print(escape(f"guard: {loop.guard_report.summary()}"), style="yellow")
        for st in r.steps:
            o.print()
            o.print(f"step {st.index + 1}", style="bold")
            o.print(escape(st.reply.strip() or "(empty reply)"))
            for c in st.parsed.calls:
                o.print(
                    escape(
                        f"  call {c.resolved_name or c.name} {json.dumps(c.arguments, ensure_ascii=False)}: "
                        f"{'valid' if c.valid else 'invalid'}"
                    )
                )
                for problem in [] if c.valid else validation_problems(c.validation):
                    o.print(escape(f"    {problem}"), style="yellow")
            for c in st.parsed.rejected:
                o.print(escape(f"  rejected {c.name}: {c.reason}"), style="red")
            for ex in st.executed:
                body = ex.get("result") if ex.get("ok") else ex.get("error")
                o.print(
                    escape(
                        f"  ran {ex['name']}: {'ok' if ex.get('ok') else 'failed'} "
                        f"{json.dumps(body, ensure_ascii=False, default=str)}"
                    )
                )
        o.print()
        if r.final_text:
            o.print("final answer", style="bold")
            o.print(escape(r.final_text))
        o.print(
            f"stopped: {r.stopped}; {r.prompt_tokens:,} prompt and {r.completion_tokens:,} completion tokens; "
            f"cost {r.cost:.6f} (relative units)"
        )
        if r.error:
            o.print(escape(f"error: {r.error}"), style="red")

    emit(result, as_json=as_json, render=show)
    if result.stopped == "error":
        raise typer.Exit(4)


# --------------------------------------------------------------------------- #
# ab-test
# --------------------------------------------------------------------------- #


@app.command("ab-test", rich_help_panel=PANEL_CHOOSE)
@handle_errors
def ab_test_cmd(
    base_url: str = typer.Option(..., "--base-url", help="An OpenAI-compatible base URL."),
    model: str = typer.Option(..., "--model", help="The model name the endpoint serves."),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="The variable holding the API key."),
    formats: Optional[str] = typer.Option(
        None, "--formats", help="Comma-separated format ids; default the eight core formats."
    ),
    n_requests: int = typer.Option(50, "--n-requests", min=1, help="Generated requests per format."),
    n_tools: int = typer.Option(8, "--n-tools", min=1),
    tier: int = typer.Option(3, "--tier", min=1, max=5),
    seed: int = typer.Option(0, "--seed"),
    rule: Rule = typer.Option(Rule.symmetric, "--rule", help="The paper recommends symmetric for measurement."),
    tools_file: Optional[str] = typer.Option(None, "--tools-file", help="Your tools, with --examples."),
    examples: Optional[str] = typer.Option(None, "--examples", help="Labelled requests, one JSON per line."),
    source: Kind = FROM_OPT,
    concurrency: int = typer.Option(4, "--concurrency", min=1),
    max_tokens: int = typer.Option(512, "--max-tokens", min=1),
    thinking: Optional[bool] = typer.Option(
        None,
        "--thinking/--no-thinking",
        help="The chat template's thinking switch (vLLM). Default: off for "
        "Qwen 3 and Qwen 3.5, as in the study; not sent otherwise.",
    ),
    out: Optional[str] = typer.Option(None, "--out", help="Write the report JSON, with every record, here."),
    as_json: bool = JSON_OPT,
) -> None:
    """Measure eight formats on your own endpoint and pick the best (the study's "measure eight")."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

    from ..advisor.measure import ab_test, load_examples
    from ..sdk.client import OpenAICompatClient

    if (tools_file is None) != (examples is None):
        raise typer.BadParameter("--tools-file and --examples go together", param_hint="--examples")
    ts = _load(tools_file, source) if tools_file else None
    exs = load_examples(examples) if examples else None
    fmts = list(dict.fromkeys(_split(formats) or list(CORE_FORMATS)))
    from ..sdk.rendering import check_format

    for f in fmts:
        check_format(f)
    thinking = _thinking_default(model, thinking)
    client = OpenAICompatClient(base_url, model, api_key_env=api_key_env or "OPENAI_API_KEY", enable_thinking=thinking)
    if not client.health():
        raise ClientError(
            f"{base_url.rstrip('/')} did not answer GET /models; check --base-url and that the "
            f"server is up (toolform doctor --base-url URL checks it)"
        )
    per = len(exs) if exs is not None else n_requests
    total = per * len(fmts)
    err = console(stderr=True)
    tty = sys.stderr.isatty()
    progress_ui = Progress(
        TextColumn("measuring"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=err,
        transient=True,
        disable=as_json or not tty,
    )
    step = max(1, total // 10)

    def on_progress(done: int, tot: int) -> None:
        progress_ui.update(task, completed=done)
        if not tty and not as_json and (done % step == 0 or done == tot):
            err.print(f"measured {done} of {tot} requests", markup=False)

    with progress_ui:
        task = progress_ui.add_task("requests", total=total)
        report = ab_test(
            client,
            formats=fmts,
            n_requests=n_requests,
            n_tools=n_tools,
            tier=tier,
            seed=seed,
            rule=rule.value,
            toolset=ts,
            examples=exs,
            max_tokens=max_tokens,
            concurrency=concurrency,
            keep_records=bool(out),
            progress=on_progress,
            preflight=False,
        )
    if out:
        _write(out, dumps(report))

    def show(r: Any) -> None:
        o = console()
        table(
            [
                {
                    "format": s.format_id,
                    "protocol": s.protocol_id,
                    "accuracy": pct(s.accuracy),
                    "Wilson 95%": f"[{s.interval[0]:.1f}, {s.interval[1]:.1f}]",
                    "strict parse": pct(s.parse_strict),
                    "hallucinated": pct(s.hallucinated),
                    "prompt tokens": f"{s.prompt_tokens_mean:,.0f}",
                    "errors": str(s.errors) if s.errors else "",
                    "cut off": str(s.truncated) if s.truncated else "",
                }
                for s in r.scores
            ],
            [
                "format",
                "protocol",
                "accuracy",
                "Wilson 95%",
                "strict parse",
                "hallucinated",
                "prompt tokens",
                "errors",
                "cut off",
            ],
            title=f"{r.model}: {r.n_requests} {r.source} requests per format, {r.rule} rule",
        )
        best = r.scores[0]
        o.print()
        if r.verdict == "winner":
            o.print(escape(f"Winner: {r.winner} with {r.winner_protocol}, {best.accuracy:.2f}%."), style="bold")
            if r.tied_with:
                o.print(escape(f"Tied with (overlapping intervals): {', '.join(r.tied_with)}."))
        else:
            head = "No difference measured" if r.verdict == "no_difference" else "Inconclusive"
            o.print(escape(f"{head}: {r.verdict_reason}"), style="bold yellow")
        if any(s.truncated for s in r.scores):
            o.print(
                escape(
                    "Some replies were cut off at --max-tokens and count as wrong; raise it, or turn "
                    "thinking off with --no-thinking."
                ),
                style="yellow",
            )
        f = _facts()
        o.print(
            escape(
                f"In the study, measuring eight formats this way reached {f['measure_eight']:.2f}%, against "
                f"{f['fitted_rule']:.2f}% for the fitted rule and {f['always_json']:.2f}% for the JSON "
                f"Schema default."
            ),
            style="dim",
        )
        if out:
            o.print(escape(f"Wrote the report to {out}."))

    emit(report, as_json=as_json, render=show)
    if report.verdict == "inconclusive":
        raise typer.Exit(4)


def _thinking_default(model: str, thinking: bool | None) -> bool | None:
    """Off for Qwen 3 and Qwen 3.5 unless asked, as in the study; otherwise not sent."""
    if thinking is not None:
        return thinking
    from ..advisor import resolve_model
    from ..advisor.recommend import THINKING_FAMILIES

    if resolve_model(model).family in THINKING_FAMILIES:
        warn(f"thinking is off for {model}, as in the study; pass --thinking to turn it on")
        return False
    return None


# --------------------------------------------------------------------------- #
# evidence
# --------------------------------------------------------------------------- #


def _fact_text(f: dict[str, Any]) -> str:
    """A headline fact's value as the paper prints it: percent and ratios to two decimals."""
    v, unit = f.get("value"), f.get("unit")
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return str(v)
    if unit == "%":
        return f"{v:.2f}%"
    if unit == "ratio":
        return f"{v:.2f}"
    if unit == "count":
        return f"{int(v):,}" if float(v).is_integer() else str(v)
    return str(v)


def _fmt_value(v: Any) -> str:
    if isinstance(v, dict) and "value" in v:
        iv = v.get("interval")
        base = f"{v['value']}"
        return f"{base} [{iv[0]}, {iv[1]}]" if iv else base
    if isinstance(v, dict):
        s = json.dumps(v, ensure_ascii=False)
    elif isinstance(v, (list, tuple)):
        s = ", ".join(_fmt_value(x) for x in v)
    elif v is None:
        s = ""
    else:
        s = str(v)
    return s if len(s) <= 80 else s[:77] + "..."


def _is_num_list(v: Any) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)


def _is_scalar(v: Any) -> bool:
    return not isinstance(v, (dict, list, tuple))


_ENTRY_COLUMNS = ("id", "name", "family", "default_protocol", "novel", "core", "in_study", "structured", "in_crossing")


def _show_evidence_data(name: str, data: Any, depth: int = 0) -> None:
    """A readable view of any evidence file: lists of rows as tables, series as grids, the rest as lines."""
    o = console()
    if isinstance(data, list):
        _rows_table(name, data)
        return
    if not isinstance(data, dict):
        o.print(escape(f"{name}: {_fmt_value(data)}"))
        return
    if data and all(isinstance(v, dict) and "id" in v for v in data.values()):
        # An id -> entry table, such as formats or protocols.
        rows = []
        for v in data.values():
            row = {c: v.get(c) for c in _ENTRY_COLUMNS if c in v}
            measured = v.get("measured")
            if isinstance(measured, dict) and "call_exact" in measured:
                row["measured"] = measured["call_exact"]
            rows.append(row)
        _rows_table(name, rows)
        return
    for key, v in data.items():
        label = f"{name}.{key}"
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            _rows_table(label, v)
        elif isinstance(v, dict) and v and all(_is_num_list(x) for x in v.values()):
            length = len(next(iter(v.values())))
            header = next(
                (data[h] for h in data if h != key and _is_num_list(data[h]) and len(data[h]) == length),
                list(range(1, length + 1)),
            )
            cols = [str(h) for h in header]
            table(
                [{"row": k, **{c: _fmt_value(x) for c, x in zip(cols, vals, strict=False)}} for k, vals in v.items()],
                ["row", *cols],
                title=label,
            )
        elif (
            isinstance(v, dict)
            and v
            and all(isinstance(x, dict) and all(_is_scalar(y) for y in x.values()) for x in v.values())
        ):
            inner = list(dict.fromkeys(k2 for x in v.values() for k2 in x))
            outer = list(v)
            if len(outer) >= len(inner):
                table(
                    [{"row": r, **{c: _fmt_value(v[r].get(c)) for c in inner}} for r in outer],
                    ["row", *inner],
                    title=label,
                )
            else:
                table(
                    [{"row": r, **{c: _fmt_value(v[c].get(r)) for c in outer}} for r in inner],
                    ["row", *outer],
                    title=label,
                )
        elif isinstance(v, dict) and v and all(_is_scalar(x) for x in v.values()):
            o.print(escape(f"{label}: " + ", ".join(f"{k} {_fmt_value(x)}" for k, x in v.items())))
        elif isinstance(v, dict) and depth < 3:
            _show_evidence_data(label, v, depth + 1)
            continue
        else:
            o.print(escape(f"{label}: {_fmt_value(v)}"))
        o.print()


def _rows_table(title: str, rows: list[dict[str, Any]]) -> None:
    cols: list[str] = []
    for r in rows:
        for k, v in r.items():
            if k not in cols and not (isinstance(v, str) and len(v) > 200):
                cols.append(k)
    cols = cols[:10]
    table([{c: _fmt_value(r.get(c)) for c in cols} for r in rows], cols, title=title)


@app.command("evidence", rich_help_panel=PANEL_CHOOSE)
@handle_errors
def evidence_cmd(
    name: Optional[str] = typer.Argument(None, help="An evidence file, for example families or protocol_crossing."),
    list_files: bool = typer.Option(False, "--list", help="List the evidence files."),
    fact: Optional[str] = typer.Option(None, "--fact", help="One headline fact by id."),
    as_json: bool = JSON_OPT,
) -> None:
    """Show the study's evidence: the headline facts, a file as a table, or one fact."""
    from ..advisor.evidence import load_evidence

    ev = load_evidence()
    if list_files:
        manifest = ev.load("manifest")

        def show_files(_: Any) -> None:
            table(
                [
                    {"name": f["name"], "bytes": f"{f['bytes']:,}", "source": ", ".join(f.get("source") or [])}
                    for f in manifest["files"]
                ],
                ["name", "bytes", "source"],
                title=f"Evidence {manifest['evidence_version']}",
            )

        emit(manifest, as_json=as_json, render=show_files)
        return
    if fact:
        one = ev.fact(fact)

        def show_fact(f: Any) -> None:
            unit = "" if f.get("unit") in ("%", "ratio", "count", None) else f" {f['unit']}"
            console().print(escape(f"{f['id']}: {_fact_text(f)}{unit}  {f['text']}  ({f['source']})"))

        emit(one, as_json=as_json, render=show_fact)
        return
    if name:
        doc = ev.load(name)

        def show_file(d: Any) -> None:
            o = console()
            o.print(escape(f"{d.get('name', name)}: {d.get('description', '')}"), style="bold")
            src = d.get("source")
            if src:
                o.print(escape(f"source: {src if isinstance(src, str) else ', '.join(map(str, src))}"), style="dim")
            o.print()
            _show_evidence_data(name, d.get("data"))

        emit(doc, as_json=as_json, render=show_file)
        return
    facts = ev.facts()

    def show_facts(fs: Any) -> None:
        table(
            [{"id": f["id"], "value": _fact_text(f), "text": f["text"], "source": f["source"]} for f in fs],
            ["id", "value", "text", "source"],
            title=f"Headline facts (evidence {ev.version})",
        )

    emit(facts, as_json=as_json, render=show_facts)


# --------------------------------------------------------------------------- #
# serve
# --------------------------------------------------------------------------- #


@app.command("serve", rich_help_panel=PANEL_OPERATE)
@handle_errors
def serve_cmd(
    host: Optional[str] = typer.Option(None, "--host", help="Default 127.0.0.1."),
    port: Optional[int] = typer.Option(None, "--port", min=1, max=65535, help=f"Default {DEFAULT_PORT}."),
    endpoint: Optional[str] = typer.Option(None, "--endpoint", help="OpenAI-compatible base URL for ab-test."),
    endpoint_model: Optional[str] = typer.Option(None, "--endpoint-model", help="The model that endpoint serves."),
    endpoint_key_env: Optional[str] = typer.Option(
        None, "--endpoint-key-env", help="The variable holding that endpoint's key."
    ),
    allow_client_endpoints: bool = typer.Option(
        False, "--allow-client-endpoints", help="Let a request name its own base_url (off by default)."
    ),
    cors: Optional[List[str]] = typer.Option(None, "--cors", help="An allowed browser origin; repeat for more."),
    allowed_host: Optional[List[str]] = typer.Option(
        None,
        "--allowed-host",
        help="A host name the server answers to besides localhost, "
        "127.0.0.1 and ::1 (a proxy's name, say); repeat for "
        "more; * turns the check off.",
    ),
    reload: bool = typer.Option(False, "--reload", help="Restart on code changes (development)."),
    as_json: bool = typer.Option(False, "--json", help="Print the settings as JSON instead of the banner, then serve."),
) -> None:
    """Start the HTTP API behind the dashboard (needs the serve extra)."""
    from .info import serve_extra_available

    ok, why = serve_extra_available()
    if not ok:
        error(f'toolform serve needs the serve extra: pip install "toolform[serve]" ({why})')
        raise typer.Exit(3)
    from ..serve import ServeConfig, run

    cfg = ServeConfig.from_env()
    if host:
        cfg.host = host
    if port:
        cfg.port = port
    if endpoint:
        cfg.endpoint = endpoint
    if endpoint_model:
        cfg.endpoint_model = endpoint_model
    if endpoint_key_env is not None:
        cfg.endpoint_api_key_env = endpoint_key_env or None
    if allow_client_endpoints:
        cfg.allow_client_endpoints = True
    if cors:
        cfg.cors_origins = tuple(dict.fromkeys([*cfg.cors_origins, *cors]))
    if allowed_host:
        cfg.allowed_hosts = tuple(dict.fromkeys([*cfg.allowed_hosts, *allowed_host]))
    shown = "localhost" if cfg.host in ("0.0.0.0", "::") else cfg.host
    url = f"http://{shown}:{cfg.port}"
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        warn("the API has no authentication; bind to 127.0.0.1 unless every machine that can reach it is trusted")

    def banner(_: Any) -> None:
        say(f"ToolForm API on {url} (docs at /docs, OpenAPI at /openapi.json)")
        if cfg.endpoint:
            say(f"ab-test measures {cfg.endpoint_model or '(model named per request)'} at {cfg.endpoint}")

    emit(
        {"url": url, "docs": f"{url}/docs", "openapi": f"{url}/openapi.json", "settings": cfg.to_dict()},
        as_json=as_json,
        render=banner,
    )
    run(cfg, reload=reload)


# --------------------------------------------------------------------------- #
# doctor and version
# --------------------------------------------------------------------------- #


def doctor_checks(base_url: str | None = None) -> list[dict[str, str]]:
    """Every check of ``toolform doctor``: ``{"name", "status" (ok, warn, fail), "detail"}``."""
    from .info import installed_version, serve_extra_available, version_info

    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    py = sys.version_info
    add("python", "ok" if py >= (3, 10) else "fail", f"{py.major}.{py.minor}.{py.micro} (3.10 or newer needed)")
    try:
        v = version_info()
        inst = installed_version()
        detail = f"toolform {v['framework']}, evidence {v['evidence']}"
        if inst is None:
            add("versions", "warn", detail + "; the package is not installed (running from a source tree)")
        elif inst != FRAMEWORK_VERSION:
            add("versions", "warn", detail + f"; the installed metadata says {inst}, reinstall with pip install -e .")
        else:
            add("versions", "ok", detail)
    except Exception as exc:  # noqa: BLE001 - doctor reports, it does not raise
        add("versions", "fail", f"{type(exc).__name__}: {exc}")
    try:
        from ..advisor.evidence import DATA_DIR, load_evidence

        manifest = load_evidence().load("manifest")
        bad = []
        for f in manifest["files"]:
            p = DATA_DIR / f["path"]
            if not p.is_file():
                bad.append(f"{f['name']} missing")
            elif hashlib.sha256(p.read_bytes()).hexdigest() != f["sha256"]:
                bad.append(f"{f['name']} changed")
        add(
            "evidence",
            "fail" if bad else "ok",
            "; ".join(bad)
            if bad
            else f"{len(manifest['files'])} files match the manifest ({manifest['evidence_version']})",
        )
    except Exception as exc:  # noqa: BLE001
        add("evidence", "fail", f"{type(exc).__name__}: {exc}")
    try:
        from ..formats import format_ids

        ids = format_ids()
        study = [f for f in ids if f not in TWO_STAGE_FORMATS]
        want = STUDY_FORMAT_COUNT + len(TWO_STAGE_FORMATS)
        add(
            "formats",
            "ok" if len(ids) == want and len(study) == STUDY_FORMAT_COUNT else "fail",
            f"{len(ids)} registered ({len(study)} in the study plus {len(ids) - len(study)} two-stage variants)",
        )
    except Exception as exc:  # noqa: BLE001
        add("formats", "fail", f"{type(exc).__name__}: {exc}")
    try:
        from ..protocols import protocol_ids

        n = len(protocol_ids())
        add("protocols", "ok" if n == STUDY_PROTOCOL_COUNT else "fail", f"{n} registered")
    except Exception as exc:  # noqa: BLE001
        add("protocols", "fail", f"{type(exc).__name__}: {exc}")
    try:
        from ..sdk.rendering import render
        from ..sdk.samples import sample_toolset

        ts = sample_toolset()
        broken = []
        for fid in CORE_FORMATS:
            try:
                render(ts, fid)
            except Exception as exc:  # noqa: BLE001
                broken.append(f"{fid} ({type(exc).__name__})")
        add(
            "rendering",
            "fail" if broken else "ok",
            ("broken: " + ", ".join(broken)) if broken else "the eight core formats render the sample tool",
        )
    except Exception as exc:  # noqa: BLE001
        add("rendering", "fail", f"{type(exc).__name__}: {exc}")
    ok, why = serve_extra_available()
    add("serve extra", "ok" if ok else "warn", why if ok else f'{why}; pip install "toolform[serve]" for the API')
    if base_url:
        from ..sdk.client import OpenAICompatClient

        healthy = OpenAICompatClient(base_url, "", max_retries=0).health()
        add(
            "endpoint",
            "ok" if healthy else "fail",
            f"GET {base_url.rstrip('/')}/models " + ("answered" if healthy else "did not answer 200"),
        )
    return checks


@app.command("doctor", rich_help_panel=PANEL_OPERATE)
@handle_errors
def doctor_cmd(
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Also check this OpenAI-compatible endpoint."),
    as_json: bool = JSON_OPT,
) -> None:
    """Check the install: Python, versions, evidence, registries, rendering, the serve extra, an endpoint."""
    checks = doctor_checks(base_url)
    ok = all(c["status"] != "fail" for c in checks)
    result = {"ok": ok, "checks": checks}

    def show(_: Any) -> None:
        o = console()
        for c in checks:
            style = {"ok": "green", "warn": "yellow", "fail": "red"}[c["status"]]
            o.print(f"[{style}]{c['status']:<4}[/{style}] {escape(c['name']):<12} {escape(c['detail'])}")
        o.print("all checks passed" if ok else "some checks failed", style="bold")

    emit(result, as_json=as_json, render=show)
    if not ok:
        raise typer.Exit(1)


@app.command("version", rich_help_panel=PANEL_OPERATE)
@handle_errors
def version_cmd(as_json: bool = JSON_OPT) -> None:
    """Print the toolform and evidence versions."""
    from .info import version_info

    v = version_info()

    def show(d: Any) -> None:
        sys.stdout.write(f"toolform {d['framework']}, evidence {d['evidence']}, Python {d['python']}\n")

    emit(v, as_json=as_json, render=show)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> None:
    """The ``toolform`` console script. Like any typer app, it ends with ``SystemExit``."""
    args = list(sys.argv[1:] if argv is None else argv)
    app(args=args, prog_name="toolform")


__all__ = ["app", "doctor_checks", "handle_errors", "main"]
