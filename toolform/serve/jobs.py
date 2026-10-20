"""Background jobs for long requests (the eight-format measurement).

A job is a function that takes a progress callback ``progress(done, total)``
and returns a JSON-safe dict. Jobs run on a small thread pool; their state
lives in memory and is lost when the server stops.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

JobFn = Callable[[Callable[[int, int], None]], dict[str, Any]]

STATUSES: tuple[str, ...] = ("queued", "running", "done", "failed", "cancelled")

log = logging.getLogger("toolform.serve.jobs")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobStore:
    """Runs jobs on a thread pool and remembers their state.

    ``get`` returns a copy: ``{"id", "status", "done", "total", "result",
    "error", "created_at"}``. At most ``keep`` finished jobs are kept; the
    oldest finished ones are forgotten first.
    """

    def __init__(self, max_workers: int = 4, *, keep: int = 200) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="toolform-job")
        self._jobs: dict[str, dict[str, Any]] = {}
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._keep = keep
        self.max_workers = max_workers

    def submit(self, fn: JobFn, *, total: int = 0, cancel: threading.Event | None = None) -> str:
        """Queue ``fn`` and return the job id (a uuid4 hex string).

        ``cancel`` is the event :meth:`cancel` sets; ``fn`` should watch it and stop.
        """
        job_id = uuid.uuid4().hex
        event = cancel or threading.Event()
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "status": "queued",
                "done": 0,
                "total": int(total),
                "result": None,
                "error": None,
                "created_at": _now(),
            }
            self._events[job_id] = event
            self._prune()

        def progress(done: int, tot: int) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job["done"], job["total"] = int(done), int(tot)

        def work() -> None:
            with self._lock:
                if event.is_set():
                    self._jobs[job_id]["status"] = "cancelled"
                    return
                self._jobs[job_id]["status"] = "running"
            try:
                result = fn(progress)
            except Exception as exc:  # noqa: BLE001 - a failed job is reported, never raised
                cancelled = event.is_set()
                if not cancelled:
                    log.exception("job %s failed", job_id)
                with self._lock:
                    job = self._jobs[job_id]
                    job["status"] = "cancelled" if cancelled else "failed"
                    job["error"] = None if cancelled else f"{type(exc).__name__}: {exc}"
                    job["traceback"] = traceback.format_exc(limit=5)
                return
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "done"
                job["result"] = result
                if job["total"]:
                    job["done"] = job["total"]

        self._pool.submit(work)
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        """A copy of the job's state, or None for an unknown id."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {k: v for k, v in job.items() if k != "traceback"}

    def list(self) -> list[dict[str, Any]]:
        """Every remembered job, newest first, without results."""
        with self._lock:
            jobs = [{k: v for k, v in j.items() if k not in ("result", "traceback")} for j in self._jobs.values()]
        return sorted(jobs, key=lambda j: j["created_at"], reverse=True)

    def active(self) -> int:
        """How many jobs are queued or running."""
        with self._lock:
            return sum(1 for j in self._jobs.values() if j["status"] in ("queued", "running"))

    def queued(self) -> int:
        """How many jobs wait for a free worker."""
        with self._lock:
            return sum(1 for j in self._jobs.values() if j["status"] == "queued")

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        """Ask a job to stop: a queued job never starts, a running one stops before its next request.

        Returns the job's state, or None for an unknown id. A finished job is left as it is.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job["status"] in ("queued", "running"):
                self._events[job_id].set()
                if job["status"] == "queued":
                    job["status"] = "cancelled"
            return {k: v for k, v in job.items() if k != "traceback"}

    def _prune(self) -> None:
        finished = [k for k, j in self._jobs.items() if j["status"] in ("done", "failed", "cancelled")]
        extra = len(finished) - self._keep
        for k in finished[: max(0, extra)]:
            del self._jobs[k]
            self._events.pop(k, None)

    def shutdown(self, wait: bool = False) -> None:
        """Stop taking jobs; with ``wait``, let running ones finish."""
        self._pool.shutdown(wait=wait, cancel_futures=not wait)


__all__ = ["JobStore", "STATUSES"]
