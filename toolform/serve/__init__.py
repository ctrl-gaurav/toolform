"""The HTTP API behind the dashboard and the CLI's ``serve`` command.

It needs the ``serve`` extra (FastAPI, uvicorn, pydantic)::

    pip install "toolform[serve]"
    toolform serve                 # http://127.0.0.1:8765, docs at /docs

``create_app`` builds the app, ``run`` serves it.
"""

from __future__ import annotations

SERVE_EXTRA_MESSAGE = 'toolform.serve needs the serve extra: pip install "toolform[serve]"'

try:
    import fastapi  # noqa: F401
    import pydantic  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(SERVE_EXTRA_MESSAGE) from exc

from .app import create_app, create_app_from_env, run  # noqa: E402
from .config import ServeConfig  # noqa: E402
from .jobs import JobStore  # noqa: E402

__all__ = ["JobStore", "SERVE_EXTRA_MESSAGE", "ServeConfig", "create_app", "create_app_from_env", "run"]
