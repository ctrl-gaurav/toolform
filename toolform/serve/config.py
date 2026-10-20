"""Configuration of the HTTP API.

Every field has a safe default: the server binds to 127.0.0.1, accepts
browser calls only from the public site and local development servers, and
lets no request name its own model endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import Any, Mapping

from ..sdk.constants import DEFAULT_PORT

DEFAULT_CORS: tuple[str, ...] = (
    "https://ctrl-gaurav.github.io",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)

#: Environment variables read by :meth:`ServeConfig.from_env`, and the field each sets.
ENV_VARS: dict[str, str] = {
    "TOOLFORM_HOST": "host",
    "TOOLFORM_PORT": "port",
    "TOOLFORM_CORS": "cors_origins",
    "TOOLFORM_ENDPOINT": "endpoint",
    "TOOLFORM_ENDPOINT_MODEL": "endpoint_model",
    "TOOLFORM_ENDPOINT_KEY_ENV": "endpoint_api_key_env",
    "TOOLFORM_ALLOW_CLIENT_ENDPOINTS": "allow_client_endpoints",
    "TOOLFORM_MAX_TOOLS": "max_tools",
    "TOOLFORM_MAX_TEXT_CHARS": "max_text_chars",
    "TOOLFORM_MAX_BODY_BYTES": "max_body_bytes",
    "TOOLFORM_MAX_JOBS": "max_jobs",
    "TOOLFORM_MAX_AB_REQUESTS": "max_ab_requests",
    "TOOLFORM_ALLOWED_HOSTS": "allowed_hosts",
}

#: Host names every server answers to. A request with any other Host header is refused (421), which
#: stops a page that rebinds its own domain to 127.0.0.1 from reaching the API.
LOCAL_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _bool(name: str, value: str) -> bool:
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ValueError(f"{name} must be one of 1, 0, true, false, yes, no, on, off; got {value!r}")


def _int(name: str, value: str, minimum: int = 1) -> int:
    try:
        n = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number; got {value!r}") from exc
    if n < minimum:
        raise ValueError(f"{name} must be at least {minimum}; got {n}")
    return n


@dataclass
class ServeConfig:
    """Settings of one server.

    ``endpoint`` is the OpenAI-compatible base URL the ``ab-test`` route
    measures; without it that route answers 409. ``allow_client_endpoints``
    lets a request name its own ``base_url``; it is off by default because a
    server that fetches any URL a caller names can be turned against the
    network it runs in. ``max_tools`` and ``max_text_chars`` bound one
    request's tools and text, and ``max_body_bytes`` its raw size; over any
    of them the answer is 413. ``max_jobs`` is how many measurements run at
    once; as many more may wait, and past that the answer is 429.
    ``max_ab_requests`` bounds one measurement (formats times requests).
    ``allowed_hosts`` adds host names the server answers to besides
    localhost, 127.0.0.1, ::1 and ``host``; ``*`` turns the check off.
    """

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    cors_origins: tuple[str, ...] = DEFAULT_CORS
    endpoint: str | None = None
    endpoint_model: str | None = None
    endpoint_api_key_env: str | None = "OPENAI_API_KEY"
    allow_client_endpoints: bool = False
    max_tools: int = 2000
    max_text_chars: int = 1_000_000
    max_body_bytes: int = 8_000_000
    max_jobs: int = 4
    max_ab_requests: int = 20_000
    allowed_hosts: tuple[str, ...] = ()

    def host_names(self) -> tuple[str, ...]:
        """Every host name this server answers to, or ``("*",)`` when the check is off."""
        if "*" in self.allowed_hosts:
            return ("*",)
        names = list(LOCAL_HOSTS)
        if self.host not in ("0.0.0.0", "::", ""):
            names.append(self.host)
        names.extend(h for h in self.allowed_hosts if h)
        return tuple(dict.fromkeys(n.strip("[]").lower() for n in names))

    @property
    def endpoint_configured(self) -> bool:
        """Whether the server has its own model endpoint for measurements."""
        return bool(self.endpoint)

    def to_dict(self) -> dict[str, Any]:
        """The settings as JSON-safe data. The API key's value is never included, only its variable's name."""
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["cors_origins"] = list(self.cors_origins)
        d["allowed_hosts"] = list(self.allowed_hosts)
        return d

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ServeConfig":
        """Settings from ``TOOLFORM_*`` environment variables; unset ones keep their defaults.

        ``TOOLFORM_CORS`` is a comma-separated list of origins.
        ``TOOLFORM_ENDPOINT_KEY_ENV`` names the variable that holds the key
        (an empty value means no key). A malformed value raises ``ValueError``
        naming the variable.
        """
        env = os.environ if environ is None else environ
        kw: dict[str, Any] = {}
        if env.get("TOOLFORM_HOST"):
            kw["host"] = env["TOOLFORM_HOST"].strip()
        if env.get("TOOLFORM_PORT"):
            port = _int("TOOLFORM_PORT", env["TOOLFORM_PORT"])
            if port > 65535:
                raise ValueError(f"TOOLFORM_PORT must be at most 65535; got {port}")
            kw["port"] = port
        if "TOOLFORM_CORS" in env:
            kw["cors_origins"] = tuple(o.strip() for o in env["TOOLFORM_CORS"].split(",") if o.strip())
        if env.get("TOOLFORM_ENDPOINT"):
            kw["endpoint"] = env["TOOLFORM_ENDPOINT"].strip()
        if env.get("TOOLFORM_ENDPOINT_MODEL"):
            kw["endpoint_model"] = env["TOOLFORM_ENDPOINT_MODEL"].strip()
        if "TOOLFORM_ENDPOINT_KEY_ENV" in env:
            kw["endpoint_api_key_env"] = env["TOOLFORM_ENDPOINT_KEY_ENV"].strip() or None
        if "TOOLFORM_ALLOW_CLIENT_ENDPOINTS" in env:
            kw["allow_client_endpoints"] = _bool(
                "TOOLFORM_ALLOW_CLIENT_ENDPOINTS", env["TOOLFORM_ALLOW_CLIENT_ENDPOINTS"]
            )
        for var, name in (
            ("TOOLFORM_MAX_TOOLS", "max_tools"),
            ("TOOLFORM_MAX_TEXT_CHARS", "max_text_chars"),
            ("TOOLFORM_MAX_BODY_BYTES", "max_body_bytes"),
            ("TOOLFORM_MAX_JOBS", "max_jobs"),
            ("TOOLFORM_MAX_AB_REQUESTS", "max_ab_requests"),
        ):
            if env.get(var):
                kw[name] = _int(var, env[var])
        if "TOOLFORM_ALLOWED_HOSTS" in env:
            kw["allowed_hosts"] = tuple(h.strip() for h in env["TOOLFORM_ALLOWED_HOSTS"].split(",") if h.strip())
        return cls(**kw)

    def to_env(self) -> dict[str, str]:
        """The ``TOOLFORM_*`` variables that rebuild these settings with :meth:`from_env`."""
        out = {
            "TOOLFORM_HOST": self.host,
            "TOOLFORM_PORT": str(self.port),
            "TOOLFORM_CORS": ",".join(self.cors_origins),
            "TOOLFORM_ENDPOINT_KEY_ENV": self.endpoint_api_key_env or "",
            "TOOLFORM_ALLOW_CLIENT_ENDPOINTS": "1" if self.allow_client_endpoints else "0",
            "TOOLFORM_MAX_TOOLS": str(self.max_tools),
            "TOOLFORM_MAX_TEXT_CHARS": str(self.max_text_chars),
            "TOOLFORM_MAX_BODY_BYTES": str(self.max_body_bytes),
            "TOOLFORM_MAX_JOBS": str(self.max_jobs),
            "TOOLFORM_MAX_AB_REQUESTS": str(self.max_ab_requests),
            "TOOLFORM_ALLOWED_HOSTS": ",".join(self.allowed_hosts),
        }
        if self.endpoint:
            out["TOOLFORM_ENDPOINT"] = self.endpoint
        if self.endpoint_model:
            out["TOOLFORM_ENDPOINT_MODEL"] = self.endpoint_model
        return out


__all__ = ["DEFAULT_CORS", "ENV_VARS", "LOCAL_HOSTS", "ServeConfig"]
