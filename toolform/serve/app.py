"""The FastAPI application: routes, the one error shape, CORS and body limits.

``create_app`` builds an app from a :class:`ServeConfig`; ``run`` serves it
with uvicorn. The dashboard on the public site can call a server on the
user's own machine: CORS allows the site's origin, and a preflight that asks
for private-network access gets ``Access-Control-Allow-Private-Network: true``.
"""

from __future__ import annotations

import inspect
import json
import logging
import math
import os
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..sdk.client import ChatClient, OpenAICompatClient
from ..sdk.constants import FRAMEWORK_VERSION
from ..sdk.errors import (
    ClientError,
    EvidenceError,
    LoaderError,
    ToolFormError,
    UnknownFormatError,
    UnknownProtocolError,
)
from .config import ServeConfig
from .jobs import JobStore
from .routes import API_PREFIX, TAGS, ApiError, build_router

log = logging.getLogger("toolform.serve")

TITLE = "ToolForm API"
DESCRIPTION = (
    "ToolForm is an open-source framework that decides how an agent shows its tools to a model and reads "
    "back the calls. Give it your tools (OpenAI or MCP JSON Schema, a Python module or a TypeScript file) and "
    "your model, and it recommends a schema format and an answer protocol by combining the per-factor tables "
    "of a controlled study of 129 formats, 31 answer protocols and 112 models (model, tool count, tool "
    "complexity and protocol, each measured alone). The combination itself was not evaluated; measuring "
    "eight formats on your own model, which the ab-test route runs, is the stronger evidence.\n\n"
    'Every route is under `/api/v1`. Errors share one shape: `{"error", "detail", "status"}`.'
)

_STATUS_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "too_many_jobs",
}


def default_client_factory(
    base_url: str, model: str, api_key_env: str | None, *, enable_thinking: bool | None = None
) -> ChatClient:
    """An :class:`OpenAICompatClient` for the configured endpoint."""
    return OpenAICompatClient(base_url, model, api_key_env=api_key_env, enable_thinking=enable_thinking)


def _finite(value: Any) -> Any:
    """``value`` with every NaN or infinite float written as text, so the error body is valid JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def _debug() -> bool:
    return os.environ.get("TOOLFORM_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def _host_of(value: str) -> str:
    """The host name of a Host header, without its port; brackets of an IPv6 address removed."""
    v = value.strip().lower()
    if v.startswith("["):
        return v[1 : v.index("]")] if "]" in v else v[1:]
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


class HostCheckMiddleware:
    """Refuse a request whose Host header names another site (421).

    A web page can rebind its own domain to 127.0.0.1; the browser then treats
    this server as that page's own origin and CORS does not apply. Checking
    the Host header closes that door. ``names`` of ``("*",)`` turns it off.
    """

    def __init__(self, app: ASGIApp, names: tuple[str, ...]) -> None:
        self.app = app
        self.names = set(names)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or "*" in self.names:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        host = _host_of(headers.get(b"host", b"").decode("latin-1"))
        if host not in self.names:
            resp = _error(
                421,
                "misdirected_request",
                f"this server does not answer to the host {host!r}; add it "
                f"with --allowed-host or TOOLFORM_ALLOWED_HOSTS",
            )
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _error(status: int, error: str, detail: Any, *, line: int | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": error, "detail": jsonable_encoder(detail), "status": status}
    if line is not None:
        body["line"] = line
    return JSONResponse(status_code=status, content=body)


class BodyLimitMiddleware:
    """Answer 413 when a request body is larger than ``limit`` bytes.

    A declared ``Content-Length`` is checked before anything is read; a body
    without one is read up to the limit and replayed to the app.
    """

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def _reject(self, scope: Scope, receive: Receive, send: Send, size: str) -> None:
        resp = _error(413, "payload_too_large", f"the request body is {size} bytes; the limit is {self.limit:,}")
        await resp(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                n = int(declared)
            except ValueError:
                resp = _error(400, "bad_request", "the Content-Length header is not a whole number")
                await resp(scope, receive, send)
                return
            if n > self.limit:
                await self._reject(scope, receive, send, f"{n:,}")
                return
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            body = message.get("body", b"")
            total += len(body)
            if total > self.limit:
                await self._reject(scope, receive, send, f"more than {self.limit:,}")
                return
            chunks.append(body)
            more = message.get("more_body", False)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class PrivateNetworkMiddleware:
    """Allow the public site to reach a server on the user's own machine.

    Browsers that implement private network access send
    ``Access-Control-Request-Private-Network: true`` on the preflight; the
    answer must carry ``Access-Control-Allow-Private-Network: true``. It is
    added only for an allowed origin.
    """

    def __init__(self, app: ASGIApp, origins: tuple[str, ...]) -> None:
        self.app = app
        self.origins = set(origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        wants = headers.get(b"access-control-request-private-network", b"").lower() == b"true"
        origin = headers.get(b"origin", b"").decode("latin-1")
        allowed = wants and ("*" in self.origins or origin in self.origins)

        async def send_with_header(message: Message) -> None:
            if allowed and message["type"] == "http.response.start":
                message = dict(message)
                headers_out = list(message.get("headers") or [])
                if not any(k.lower() == b"access-control-allow-private-network" for k, _ in headers_out):
                    headers_out.append((b"access-control-allow-private-network", b"true"))
                message["headers"] = headers_out
            await send(message)

        await self.app(scope, receive, send_with_header)


def create_app(
    config: ServeConfig | None = None, *, client_factory: Callable[..., ChatClient] | None = None
) -> FastAPI:
    """Build the API. ``client_factory(base_url, model, api_key_env)`` makes the measurement client;
    it defaults to :class:`OpenAICompatClient`, and tests pass one that returns a ``StubClient``."""
    cfg = config or ServeConfig()
    app = FastAPI(
        title=TITLE,
        version=FRAMEWORK_VERSION,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        license_info={"name": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
    )
    app.state.config = cfg
    app.state.jobs = JobStore(max_workers=cfg.max_jobs)
    app.include_router(build_router(client_factory or default_client_factory))

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {
            "name": TITLE,
            "version": FRAMEWORK_VERSION,
            "api": API_PREFIX,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": f"{API_PREFIX}/health",
        }

    # ---------------------------------------------------------------- errors
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.error, exc.detail, line=exc.line)

    @app.exception_handler(LoaderError)
    async def _loader_error(request: Request, exc: LoaderError) -> JSONResponse:
        return _error(422, "loader_error", str(exc), line=exc.line)

    @app.exception_handler(UnknownFormatError)
    async def _unknown_format(request: Request, exc: UnknownFormatError) -> JSONResponse:
        return _error(404, "unknown_format", str(exc))

    @app.exception_handler(UnknownProtocolError)
    async def _unknown_protocol(request: Request, exc: UnknownProtocolError) -> JSONResponse:
        return _error(404, "unknown_protocol", str(exc))

    @app.exception_handler(ClientError)
    async def _client_error(request: Request, exc: ClientError) -> JSONResponse:
        return _error(502, "endpoint_error", str(exc))

    @app.exception_handler(EvidenceError)
    async def _evidence_error(request: Request, exc: EvidenceError) -> JSONResponse:
        return _error(404, "not_found", str(exc))

    @app.exception_handler(ToolFormError)
    async def _toolform_error(request: Request, exc: ToolFormError) -> JSONResponse:
        return _error(400, "bad_request", str(exc))

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        return _error(400, "bad_request", str(exc))

    @app.exception_handler(KeyError)
    async def _key_error(request: Request, exc: KeyError) -> JSONResponse:
        msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else str(exc)
        return _error(400, "bad_request", msg)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = _finite(json.loads(json.dumps(jsonable_encoder(exc.errors()), default=str)))
        return _error(422, "validation_error", errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, _STATUS_CODES.get(exc.status_code, "http_error"), exc.detail)

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        detail = (
            f"{type(exc).__name__}: {exc}"
            if _debug()
            else "the server hit an unexpected error; the server log has the details"
        )
        return _error(500, "internal_error", detail)

    # ------------------------------------------------------------ middleware
    # Starlette runs the last one added first, so the order is: host check, private network, CORS, body limit.
    app.add_middleware(BodyLimitMiddleware, limit=cfg.max_body_bytes)
    cors_kwargs: dict[str, Any] = {
        "allow_origins": list(cfg.cors_origins),
        "allow_methods": ["GET", "POST", "DELETE", "OPTIONS"],
        "allow_headers": ["*"],
        "max_age": 600,
    }
    if "allow_private_network" in inspect.signature(CORSMiddleware.__init__).parameters:
        # Newer Starlette refuses a private-network preflight unless told to allow it.
        cors_kwargs["allow_private_network"] = True
    app.add_middleware(CORSMiddleware, **cors_kwargs)
    app.add_middleware(PrivateNetworkMiddleware, origins=tuple(cfg.cors_origins))
    app.add_middleware(HostCheckMiddleware, names=cfg.host_names())
    return app


def create_app_from_env() -> FastAPI:
    """An app configured from ``TOOLFORM_*`` environment variables; the factory ``--reload`` uses."""
    return create_app(ServeConfig.from_env())


def run(config: ServeConfig | None = None, *, reload: bool = False) -> None:
    """Serve the API with uvicorn. With ``reload``, the settings travel through environment variables."""
    import uvicorn

    cfg = config or ServeConfig()
    if reload:
        os.environ.update(cfg.to_env())
        uvicorn.run("toolform.serve.app:create_app_from_env", factory=True, host=cfg.host, port=cfg.port, reload=True)
        return
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)


__all__ = [
    "BodyLimitMiddleware",
    "DESCRIPTION",
    "HostCheckMiddleware",
    "PrivateNetworkMiddleware",
    "TITLE",
    "create_app",
    "create_app_from_env",
    "default_client_factory",
    "run",
]
