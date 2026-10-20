"""The routes of the HTTP API, all under ``/api/v1``.

Each route is a thin wrapper: it loads the tools, calls the SDK, and returns
the result object's ``to_dict()``. Errors are raised as :class:`ApiError` or
as the SDK's own exceptions; ``app.py`` turns both into the one error shape.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..app.info import version_info
from ..app.inputs import export_like_input, export_tools
from ..sdk.constants import FRAMEWORK_VERSION, TWO_STAGE_FORMATS
from ..sdk.errors import LoaderError, UnknownFormatError
from ..sdk.toolset import Toolset
from . import schemas as S
from .config import ServeConfig

API_PREFIX = "/api/v1"

TAGS: list[dict[str, str]] = [
    {"name": "meta", "description": "Liveness, configuration and versions."},
    {"name": "registry", "description": "The formats, protocols and models the study covered."},
    {"name": "tools", "description": "Convert tools between OpenAI, Anthropic, MCP and the canonical IR."},
    {"name": "advisor", "description": "Recommend a format and protocol from the study's evidence."},
    {"name": "render", "description": "Render tools in any of the 129 study formats."},
    {"name": "parse", "description": "Parse a reply under any of the 31 protocols and a grading rule."},
    {
        "name": "guard",
        "description": "Flag or strip instructions hidden in tool metadata. A rule-based "
        "heuristic, measured on a held-out set of 50 descriptions only; the study "
        "did not measure it.",
    },
    {"name": "catalogue", "description": "One shot, retrieval or names-first disclosure for long tool lists."},
    {
        "name": "measure",
        "description": "Measure eight formats on a model endpoint, the procedure that beat "
        "every fixed rule in the study.",
    },
    {"name": "evidence", "description": "The study's tables and headline facts, as shipped with the package."},
]

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": S.ErrorBody, "description": "Bad request"},
    404: {"model": S.ErrorBody, "description": "Unknown format, protocol or name"},
    413: {"model": S.ErrorBody, "description": "Too many tools or too much text"},
    422: {"model": S.ErrorBody, "description": "The tools could not be read, or the body is malformed"},
}


class ApiError(Exception):
    """An error with its HTTP status and code, rendered as the API's error shape."""

    def __init__(self, status: int, error: str, detail: Any, *, line: int | None = None) -> None:
        super().__init__(str(detail))
        self.status = status
        self.error = error
        self.detail = detail
        self.line = line


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _config(request: Request) -> ServeConfig:
    return request.app.state.config


def _check_text(config: ServeConfig, text: str | None, what: str) -> None:
    if text is not None and len(text) > config.max_text_chars:
        raise ApiError(
            413, "payload_too_large", f"{what} has {len(text):,} characters; the limit is {config.max_text_chars:,}"
        )


def load_http_tools(inp: S.ToolsInput, config: ServeConfig) -> Toolset:
    """Load tools sent over HTTP without ever touching the file system or running code.

    A string payload is parsed as JSON, or read as TypeScript source text; it
    is never taken as a path. ``python`` is refused.
    """
    from ..sdk.loaders import detect_kind, load_tools
    from ..sdk.typescript import from_typescript

    source = inp.source
    if source == "python":
        raise ApiError(
            400,
            "bad_request",
            "python tools are not accepted over HTTP, because loading them "
            "executes code; convert them with the CLI (toolform convert) or "
            "the SDK first",
        )
    if source not in S.HTTP_SOURCES:
        raise ApiError(400, "bad_request", f"unknown tools source {source!r}; use one of {', '.join(S.HTTP_SOURCES)}")
    payload = inp.payload
    if payload is None:
        raise ApiError(400, "bad_request", "tools.payload is empty")
    if isinstance(payload, str):
        _check_text(config, payload, "tools.payload")
        stripped = payload.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise LoaderError(
                    f"the text is not valid JSON: {exc.msg}", source="tools.payload", line=exc.lineno
                ) from exc
        elif source in ("auto", "typescript"):
            # The trailing newline keeps the loader from reading a one-line string as a file name.
            ts = Toolset.from_tools(from_typescript(payload + "\n"), name="typescript", source="typescript")
            return _check_count(ts, config)
        else:
            raise ApiError(400, "bad_request", f"a {source} payload must be JSON, not text")
    elif source == "typescript":
        raise ApiError(400, "bad_request", "a typescript payload must be the source text as a string")
    if not isinstance(payload, (dict, list)):
        raise ApiError(400, "bad_request", "tools.payload must be a JSON object, a JSON array or a string")
    n_items = _count_items(payload)
    if n_items > config.max_tools:
        raise ApiError(413, "payload_too_large", f"{n_items:,} tools; the limit is {config.max_tools:,}")
    kind = detect_kind(payload) if source == "auto" else source
    if kind not in S.HTTP_SOURCES:  # pragma: no cover - detect_kind only names python for callables
        raise ApiError(400, "bad_request", f"{kind} tools are not accepted over HTTP")
    return _check_count(load_tools(payload, kind=kind), config)


def _count_items(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        result = payload.get("result")
        inner = result if isinstance(result, dict) else payload
        tools = inner.get("tools")
        if isinstance(tools, list):
            return len(tools)
        return 1
    return 0


def _check_count(ts: Toolset, config: ServeConfig) -> Toolset:
    if len(ts) == 0:
        raise ApiError(422, "loader_error", "no tools were given; send at least one tool")
    if len(ts) > config.max_tools:
        raise ApiError(413, "payload_too_large", f"{len(ts):,} tools; the limit is {config.max_tools:,}")
    return ts


def _make_client(
    factory: Callable[..., Any], base_url: str, model: str, key_env: str | None, thinking: bool | None
) -> Any:
    """Call the client factory, passing the thinking switch only to a factory that takes it."""
    import inspect

    try:
        params = list(inspect.signature(factory).parameters.values())
    except (TypeError, ValueError):  # pragma: no cover - builtins without a signature
        params = []
    takes = any(p.name == "enable_thinking" or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    if takes:
        return factory(base_url, model, key_env, enable_thinking=thinking)
    return factory(base_url, model, key_env)


def _options(body: S.RenderOptionsBody) -> Any:
    from ..sdk.rendering import render_options

    return render_options(**body.model_dump())


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #


def build_router(client_factory: Callable[..., Any]) -> APIRouter:
    """All routes, bound to a client factory for the measurement route."""
    router = APIRouter(prefix=API_PREFIX, responses=ERROR_RESPONSES)

    # ------------------------------------------------------------------ meta
    @router.get("/health", tags=["meta"], response_model=S.HealthResponse, summary="Liveness and configuration")
    def health(request: Request) -> dict[str, Any]:
        """The server is up. Says whether a model endpoint is configured for measurements."""
        from ..advisor.evidence import load_evidence

        cfg = _config(request)
        return {
            "status": "ok",
            "version": FRAMEWORK_VERSION,
            "evidence_version": load_evidence().version,
            "endpoint_configured": cfg.endpoint_configured,
            "allow_client_endpoints": cfg.allow_client_endpoints,
        }

    @router.get("/version", tags=["meta"], response_model=S.VersionResponse, summary="Versions")
    def version() -> dict[str, str]:
        """Framework, research harness, evidence and Python versions."""
        return version_info()

    # -------------------------------------------------------------- registry
    @router.get("/formats", tags=["registry"], response_model=S.FormatsResponse, summary="Every format")
    def formats(
        core: bool | None = Query(None, description="true: only the eight core formats"),
        family: str | None = Query(None, description="Only this family, for example json or markup"),
        in_study: bool | None = Query(None, description="true: only the 129 study formats"),
    ) -> dict[str, Any]:
        """Every registered format with its metadata and its measured row from the evidence.

        133 are registered: the 129 of the study and four two-stage variants.
        """
        from ..advisor.evidence import load_evidence

        table = load_evidence().load("formats")["data"]
        rows = list(table.values())
        if core is not None:
            rows = [r for r in rows if bool(r.get("core")) == core]
        if family:
            rows = [r for r in rows if r.get("family") == family]
        if in_study is not None:
            rows = [r for r in rows if bool(r.get("in_study")) == in_study]
        return {
            "formats": rows,
            "count_in_study": sum(1 for r in table.values() if r.get("in_study")),
            "count_registered": len(table),
        }

    @router.get(
        "/formats/{format_id}",
        tags=["registry"],
        response_model=S.FormatDetail,
        summary="One format, with the sample tool rendered",
    )
    def format_detail(format_id: str) -> dict[str, Any]:
        """One format's entry, plus the paper's sample tool rendered in it with its default protocol."""
        from ..advisor.evidence import load_evidence
        from ..formats import format_ids, get_format, has_format
        from ..protocols import get_protocol
        from ..sdk.samples import sample_toolset
        from ..sdk.tokens import estimate_tokens

        table = load_evidence().load("formats")["data"]
        if format_id not in table or not has_format(format_id):
            raise UnknownFormatError(format_id, format_ids())
        entry = dict(table[format_id])
        universe = sample_toolset().universe
        fmt = get_format(format_id)
        text = fmt.render(universe)
        instructions = get_protocol(fmt.meta.default_protocol).instructions(universe)
        entry["sample"] = {"text": text, "instructions": instructions, "tokens_estimate": estimate_tokens(text)}
        if format_id in TWO_STAGE_FORMATS:
            entry["sample"]["note"] = "a two-stage selection list; use the catalogue routes to run it"
        return entry

    @router.get("/protocols", tags=["registry"], response_model=S.ProtocolsResponse, summary="Every protocol")
    def protocols() -> dict[str, Any]:
        """The 31 answer protocols with their metadata."""
        from ..advisor.evidence import load_evidence

        return {"protocols": list(load_evidence().load("protocols")["data"].values())}

    @router.get("/models", tags=["registry"], summary="The model zoo and family patterns")
    def models() -> dict[str, Any]:
        """The study's model zoo, its families, and the patterns that match a model id to a family."""
        from ..advisor.evidence import load_evidence

        return load_evidence().load("zoo")["data"]

    # ----------------------------------------------------------------- tools
    @router.post(
        "/tools/load", tags=["tools"], response_model=S.ToolsLoadResponse, summary="Convert tools to the canonical IR"
    )
    def tools_load(body: S.ToolsLoadRequest, request: Request) -> dict[str, Any]:
        """Read the tools and return them in the canonical IR, with a summary (count, tier, fingerprint)."""
        ts = load_http_tools(body.tools, _config(request))
        return {"tools": ts.to_ir()["tools"], "summary": ts.summary(), "kind": ts.source, "warnings": list(ts.warnings)}

    @router.post(
        "/tools/export", tags=["tools"], response_model=S.ToolsExportResponse, summary="Convert tools to another shape"
    )
    def tools_export(body: S.ToolsExportRequest, request: Request) -> dict[str, Any]:
        """Read the tools and write them as OpenAI, Anthropic, MCP or IR JSON."""
        ts = load_http_tools(body.tools, _config(request))
        return {"to": body.to, "payload": export_tools(ts, body.to)}

    # --------------------------------------------------------------- advisor
    @router.post(
        "/recommend", tags=["advisor"], response_model=S.RecommendationModel, summary="Recommend a format and protocol"
    )
    def recommend_route(body: S.RecommendRequest, request: Request) -> dict[str, Any]:
        """A format and protocol for a model and situation, with the expected accuracy, the range across
        the table values it rests on (not a confidence interval), the token cost, the evidence rows and a
        reason. The advisor combines the study's per-factor tables; the combination was not itself evaluated.

        With tools and no explicit ``n_tools`` or ``tier``, both come from the tools.
        """
        from ..advisor import Situation, recommend

        fields = body.situation.model_dump()
        ts = load_http_tools(body.tools, _config(request)) if body.tools is not None else None
        if ts is not None:
            given = body.situation.model_fields_set
            if "n_tools" not in given:
                fields["n_tools"] = len(ts)
            if "tier" not in given:
                fields["tier"] = ts.tier_estimate()
        situation = Situation.from_dict(fields)
        return recommend(situation, tools=ts).to_dict()

    # ---------------------------------------------------------------- render
    @router.post(
        "/render", tags=["render"], response_model=S.RenderedPromptModel, summary="Render one format and protocol"
    )
    def render_route(body: S.RenderRequest, request: Request) -> dict[str, Any]:
        """The tool block, the answer instruction and the system prompt, exactly as the study assembled
        them. With a ``request``, the chat messages too."""
        from ..sdk.rendering import render

        cfg = _config(request)
        _check_text(cfg, body.request, "request")
        ts = load_http_tools(body.tools, cfg)
        rp = render(
            ts,
            body.format,
            body.protocol,
            options=_options(body.options),
            request=body.request,
            persona=body.persona,
            null_clause=body.null_clause,
            trust_line=body.trust_line,
        )
        return rp.to_dict()

    @router.post(
        "/render/compare",
        tags=["render"],
        response_model=S.CompareResponse,
        summary="Tokens of many formats side by side",
    )
    def render_compare(body: S.CompareRequest, request: Request) -> dict[str, Any]:
        """Render every requested format (default the 129 study formats) and compare their size.
        ``study_accuracy`` is the format's main-grid accuracy from the evidence, when measured."""
        from ..sdk.rendering import compare_formats

        ts = load_http_tools(body.tools, _config(request))
        return {"rows": compare_formats(ts, body.formats, options=_options(body.options))}

    # ----------------------------------------------------------------- parse
    @router.post("/parse", tags=["parse"], response_model=S.ParsedReplyModel, summary="Parse and validate a reply")
    def parse_route(body: S.ParseRequest, request: Request) -> dict[str, Any]:
        """Parse a reply with the protocol's strict parser under a grading rule (main, symmetric or
        as_written) and validate each call against the schema."""
        from ..sdk.parse import parse_reply

        cfg = _config(request)
        _check_text(cfg, body.text, "text")
        ts = load_http_tools(body.tools, cfg)
        return parse_reply(
            body.text,
            ts,
            body.protocol,
            rule=body.rule,
            validate=body.validate_arguments,
            lenient_fallback=body.lenient_fallback,
        ).to_dict()

    # ----------------------------------------------------------------- guard
    @router.post("/guard", tags=["guard"], response_model=S.GuardReportModel, summary="Scan and clean")
    def guard_route(body: S.GuardRequest, request: Request) -> dict[str, Any]:
        """Flag instructions hidden in tool metadata and, with ``strip`` or ``drop_descriptions``, remove
        them. The default action is ``report``, which changes nothing. In the study, models followed such
        a sentence on 38.48 to 54.16% of turns in every format that shows a description. The guard is a
        heuristic: on a held-out set of 50 descriptions it flagged 12 of 25 injected ones and 1 of 25
        benign ones at high severity."""
        from ..guard import guard

        ts = load_http_tools(body.tools, _config(request))
        report = guard(
            ts,
            strictness=body.strictness,
            action=body.action.replace("-", "_"),
            scope=body.scope,
            strip_at=body.strip_at,
        )
        out = report.to_dict()
        if report.toolset is not None:
            out["cleaned"] = export_like_input(report.toolset)
        return out

    # ------------------------------------------------------------- catalogue
    @router.post(
        "/catalogue/plan",
        tags=["catalogue"],
        response_model=S.CataloguePlanModel,
        summary="One-shot, retrieval or two-stage plan",
    )
    def catalogue_plan(body: S.CataloguePlanRequest, request: Request) -> dict[str, Any]:
        """Choose how to show the catalogue, from the study's thresholds: two-stage from 64 tools or when
        the block takes more than half the window, retrieval from 32 tools, one shot below."""
        from ..catalogue import plan_catalogue

        cfg = _config(request)
        _check_text(cfg, body.query, "query")
        ts = load_http_tools(body.tools, cfg)
        return plan_catalogue(
            ts,
            format_id=body.format,
            context_tokens=body.context_tokens,
            budget_tokens=body.budget_tokens,
            query=body.query,
            k=body.k,
        ).to_dict()

    @router.post("/catalogue/retrieve", tags=["catalogue"], response_model=S.RetrievalModel, summary="BM25 ranking")
    def catalogue_retrieve(body: S.RetrieveRequest, request: Request) -> dict[str, Any]:
        """Rank the tools against the request with the study's BM25 and keep the top k. On a 128-tool
        panel, the top 8 by BM25 reached 31.19% against 12.70% for the whole panel."""
        from ..catalogue import retrieve

        cfg = _config(request)
        _check_text(cfg, body.query, "query")
        ts = load_http_tools(body.tools, cfg)
        r = retrieve(ts, body.query, k=body.k, keep=body.keep, method=body.method)
        out = r.to_dict()
        out["tools"] = r.toolset.to_ir()["tools"]
        return out

    @router.post(
        "/catalogue/two-stage/prompt",
        tags=["catalogue"],
        response_model=S.TwoStagePromptResponse,
        summary="The selection messages of names-first disclosure",
    )
    def two_stage_prompt(body: S.TwoStagePromptRequest, request: Request) -> dict[str, Any]:
        """The stage-one prompt: the catalogue as names (and descriptions), then the study's request to
        name one tool."""
        from ..catalogue import TwoStage
        from ..sdk.tokens import estimate_tokens

        cfg = _config(request)
        _check_text(cfg, body.request, "request")
        ts = load_http_tools(body.tools, cfg)
        stage = TwoStage(ts, include_descriptions=body.include_descriptions)
        msgs = stage.selection_messages(body.request)
        return {
            "messages": msgs,
            "tokens_estimate": estimate_tokens("\n".join(m.get("content") or "" for m in msgs)),
            "selection_format": stage.selection_format,
        }

    # --------------------------------------------------------------- measure
    @router.post(
        "/ab-test",
        tags=["measure"],
        status_code=202,
        response_model=S.AbTestAccepted,
        responses={
            409: {"model": S.ErrorBody, "description": "No model endpoint is configured"},
            429: {"model": S.ErrorBody, "description": "Too many measurements wait already"},
        },
        summary="Start an eight-format measurement",
    )
    def ab_test_start(body: S.AbTestRequest, request: Request) -> Any:
        """Queue the study's "measure eight" procedure on a model endpoint and return a job id.

        The server's configured endpoint is used. A request's ``base_url`` is honoured only when the
        server runs with ``--allow-client-endpoints``. Poll ``GET /api/v1/ab-test/{job_id}``; cancel with
        ``DELETE``. A repeated format runs once. Thinking is off for Qwen 3 and Qwen 3.5 unless
        ``thinking`` says otherwise, as in the study.
        """
        import threading

        from ..advisor import resolve_model
        from ..advisor.measure import Example, ab_test
        from ..advisor.recommend import THINKING_FAMILIES
        from ..sdk.constants import CORE_FORMATS
        from ..sdk.rendering import check_format

        cfg = _config(request)
        warnings: list[str] = []
        base_url = cfg.endpoint
        if body.base_url:
            if cfg.allow_client_endpoints:
                base_url = body.base_url
            else:
                warnings.append(
                    "base_url was ignored: this server does not accept client endpoints "
                    "(start it with --allow-client-endpoints to allow them)"
                )
        if not base_url:
            raise ApiError(409, "no_endpoint", "start the server with --endpoint URL --endpoint-model ID")
        model = body.model or cfg.endpoint_model
        if not model:
            raise ApiError(
                400, "bad_request", "name the model: send model, or start the server with --endpoint-model ID"
            )
        formats_ = list(dict.fromkeys(body.formats)) if body.formats else list(CORE_FORMATS)
        if body.formats and len(formats_) < len(body.formats):
            warnings.append("repeated formats run once")
        for f in formats_:
            check_format(f)
        ts = load_http_tools(body.tools, cfg) if body.tools is not None else None
        examples = None
        if body.examples is not None:
            if ts is None:
                raise ApiError(400, "bad_request", "examples need the tools they call")
            try:
                examples = [Example.from_dict(e.model_dump()) for e in body.examples]
            except (ValueError, TypeError, KeyError) as exc:
                raise ApiError(400, "bad_request", f"bad example: {exc}") from exc
            if not examples:
                raise ApiError(400, "bad_request", "examples is empty")
        per_format = len(examples) if examples is not None else body.n_requests
        total = per_format * len(formats_)
        if total > cfg.max_ab_requests:
            raise ApiError(
                413,
                "payload_too_large",
                f"{total:,} requests ({len(formats_)} formats times "
                f"{per_format}); the limit is {cfg.max_ab_requests:,}",
            )
        jobs = request.app.state.jobs
        if jobs.queued() >= cfg.max_jobs:
            raise ApiError(
                429,
                "too_many_jobs",
                f"{jobs.queued()} measurements wait already; try again when one finishes, or cancel one",
            )
        thinking = body.thinking
        if thinking is None and resolve_model(model).family in THINKING_FAMILIES:
            thinking = False
            warnings.append("thinking is off for this model, as in the study; send thinking: true to change it")
        client = _make_client(client_factory, base_url, model, cfg.endpoint_api_key_env, thinking)
        cancel = threading.Event()

        def run(progress: Callable[[int, int], None]) -> dict[str, Any]:
            report = ab_test(
                client,
                formats=formats_,
                n_requests=body.n_requests,
                n_tools=body.n_tools,
                tier=body.tier,
                seed=body.seed,
                rule=body.rule,
                toolset=ts,
                examples=examples,
                max_tokens=body.max_tokens,
                concurrency=body.concurrency,
                progress=progress,
                stop=cancel.is_set,
            )
            return report.to_dict()

        job_id = jobs.submit(run, total=total, cancel=cancel)
        return JSONResponse(
            status_code=202, content={"job_id": job_id, "status": "queued", "total": total, "warnings": warnings}
        )

    @router.get("/ab-test/{job_id}", tags=["measure"], response_model=S.JobModel, summary="Job status and result")
    def ab_test_status(job_id: str, request: Request) -> dict[str, Any]:
        """The job's status (queued, running, done, failed or cancelled), its progress, and the report when done.

        A job fails when every request failed; its report names no winner when too many failed, every
        format scored zero, or all intervals overlap."""
        job = request.app.state.jobs.get(job_id)
        if job is None:
            raise ApiError(404, "job_not_found", f"no job {job_id!r}; jobs live in memory and end with the server")
        return job

    @router.delete("/ab-test/{job_id}", tags=["measure"], response_model=S.JobModel, summary="Cancel a job")
    def ab_test_cancel(job_id: str, request: Request) -> dict[str, Any]:
        """Cancel a measurement: a queued job never starts, a running one stops before its next request."""
        job = request.app.state.jobs.cancel(job_id)
        if job is None:
            raise ApiError(404, "job_not_found", f"no job {job_id!r}; jobs live in memory and end with the server")
        return job

    # -------------------------------------------------------------- evidence
    @router.get("/evidence", tags=["evidence"], summary="The evidence manifest")
    def evidence_manifest() -> dict[str, Any]:
        """The evidence version, and each file with its sources, size and sha256."""
        from ..advisor.evidence import load_evidence

        return load_evidence().load("manifest")

    @router.get("/evidence/{name}", tags=["evidence"], summary="One evidence file")
    def evidence_file(name: str) -> dict[str, Any]:
        """One evidence file with its envelope (name, source, description, conditions, data)."""
        from ..advisor.evidence import EVIDENCE_FILES, load_evidence

        if name not in EVIDENCE_FILES:
            raise ApiError(404, "not_found", f"no evidence file {name!r}; known: {', '.join(EVIDENCE_FILES)}")
        return load_evidence().load(name)

    @router.get("/facts", tags=["evidence"], response_model=S.FactsResponse, summary="The headline facts")
    def facts() -> dict[str, Any]:
        """The study's headline facts, each checked against the paper source when the evidence was built."""
        from ..advisor.evidence import load_evidence

        return {"facts": load_evidence().facts()}

    return router


__all__ = ["API_PREFIX", "ApiError", "TAGS", "build_router", "export_like_input", "load_http_tools", "version_info"]
