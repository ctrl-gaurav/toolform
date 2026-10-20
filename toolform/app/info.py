"""Versions and install checks shared by the CLI and the HTTP API."""

from __future__ import annotations

import platform
from importlib import metadata

from ..sdk.constants import FRAMEWORK_VERSION


def version_info() -> dict[str, str]:
    """``{"framework", "evidence", "python"}``."""
    from ..advisor.evidence import load_evidence

    return {"framework": FRAMEWORK_VERSION, "evidence": load_evidence().version, "python": platform.python_version()}


def installed_version() -> str | None:
    """The version in the installed package metadata, or None when the package is not installed."""
    try:
        return metadata.version("toolform")
    except metadata.PackageNotFoundError:
        return None


def serve_extra_available() -> tuple[bool, str]:
    """Whether FastAPI, uvicorn and pydantic import; the message names what is missing."""
    missing = []
    for mod in ("fastapi", "uvicorn", "pydantic"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return False, f"missing {', '.join(missing)}"
    return True, "fastapi, uvicorn and pydantic import"


__all__ = ["installed_version", "serve_extra_available", "version_info"]
