"""The measurement route: jobs with an injected client, the 409 without an endpoint, and client endpoints."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient as _TestClient  # noqa: E402


def TestClient(app, **kw):  # noqa: N802 - a drop-in for fastapi's TestClient
    """The server answers only to local host names, so tests call it as localhost."""
    kw.setdefault("base_url", "http://localhost")
    return _TestClient(app, **kw)


from toolform.advisor.measure import load_examples  # noqa: E402
from toolform.sdk import StubClient  # noqa: E402
from toolform.sdk.constants import CORE_FORMATS  # noqa: E402
from toolform.sdk.testing import gold_answering_model  # noqa: E402
from toolform.serve import JobStore, ServeConfig, create_app  # noqa: E402
from toolform.serve import schemas as S  # noqa: E402

API = "/api/v1"
ENDPOINT = "http://127.0.0.1:9/v1"


class Factory:
    """Records what the app asked for and hands back a stub model."""

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str, str | None]] = []
        self.clients: list[StubClient] = []

    def __call__(self, base_url: str, model: str, api_key_env: str | None) -> StubClient:
        self.calls.append((base_url, model, api_key_env))
        client = StubClient(self.reply, model=model)
        self.clients.append(client)
        return client


def wait_done(client: TestClient, job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"{API}/ab-test/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def test_ab_test_job_generated_requests():
    from toolform.generator import generate_instances

    model = gold_answering_model(wrong_formats={"json_minimal"})
    model.register_instances(generate_instances(3, n_tools=4, tier=2, regime="single", seed=5))
    factory = Factory(model)
    app = create_app(ServeConfig(endpoint=ENDPOINT, endpoint_model="served-model"), client_factory=factory)
    c = TestClient(app)
    r = c.post(f"{API}/ab-test", json={"n_requests": 3, "n_tools": 4, "tier": 2, "seed": 5, "concurrency": 2})
    assert r.status_code == 202, r.text
    accepted = r.json()
    S.AbTestAccepted.model_validate(accepted)
    assert accepted["status"] == "queued" and accepted["total"] == 3 * len(CORE_FORMATS)
    assert accepted["warnings"] == []
    job = wait_done(c, accepted["job_id"])
    S.JobModel.model_validate(job)
    assert set(job) == set(S.JobModel.model_fields)
    assert job["status"] == "done", job["error"]
    assert job["done"] == job["total"] == 24
    result = job["result"]
    S.MeasureReportModel.model_validate(result)
    assert set(result) == set(S.MeasureReportModel.model_fields)
    for score in result["scores"]:
        assert set(score) == set(S.FormatScoreModel.model_fields)
    by_format = {s["format_id"]: s["accuracy"] for s in result["scores"]}
    assert by_format["json_minimal"] == 0.0
    assert all(v == 100.0 for f, v in by_format.items() if f != "json_minimal")
    assert result["winner"] != "json_minimal" and result["rule"] == "symmetric"
    assert factory.calls == [(ENDPOINT, "served-model", "OPENAI_API_KEY")]
    assert len(factory.clients[0].calls) == 24


def test_ab_test_with_examples_and_tools(fixtures_dir: Path):
    tools = json.loads((fixtures_dir / "openai_tools.json").read_text())
    examples = [e.to_dict() for e in load_examples(fixtures_dir / "examples.jsonl")]
    from toolform.sdk import Toolset

    ts = Toolset.from_openai(tools)
    model = gold_answering_model()
    for e in load_examples(fixtures_dir / "examples.jsonl"):
        model.register(e.request, e.calls, ts.universe)
    factory = Factory(model)
    c = TestClient(create_app(ServeConfig(endpoint=ENDPOINT), client_factory=factory))
    r = c.post(
        f"{API}/ab-test",
        json={
            "model": "my-model",
            "formats": ["xml_schema", "json_schema_openai"],
            "tools": {"source": "openai", "payload": tools},
            "examples": examples,
            "rule": "main",
        },
    )
    assert r.status_code == 202, r.text
    assert r.json()["total"] == 2 * len(examples)
    job = wait_done(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    assert job["result"]["source"] == "examples" and job["result"]["n_requests"] == len(examples)
    assert factory.calls[0][1] == "my-model"


def test_ab_test_no_endpoint_409():
    c = TestClient(create_app(ServeConfig()))
    r = c.post(f"{API}/ab-test", json={"model": "m"})
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "no_endpoint"
    assert body["detail"] == "start the server with --endpoint URL --endpoint-model ID"


def test_ab_test_base_url_ignored_without_permission():
    factory = Factory("no call")
    c = TestClient(create_app(ServeConfig(endpoint=ENDPOINT, endpoint_model="m"), client_factory=factory))
    r = c.post(
        f"{API}/ab-test", json={"base_url": "http://10.0.0.1:8000/v1", "n_requests": 1, "formats": ["xml_schema"]}
    )
    assert r.status_code == 202
    assert r.json()["warnings"] and "ignored" in r.json()["warnings"][0]
    assert factory.calls[0][0] == ENDPOINT
    wait_done(c, r.json()["job_id"])


def test_ab_test_base_url_alone_is_not_an_endpoint():
    c = TestClient(create_app(ServeConfig(), client_factory=Factory("x")))
    r = c.post(f"{API}/ab-test", json={"base_url": "http://10.0.0.1:8000/v1", "model": "m"})
    assert r.status_code == 409 and r.json()["error"] == "no_endpoint"


def test_ab_test_base_url_honoured_when_allowed():
    factory = Factory("no call")
    c = TestClient(create_app(ServeConfig(allow_client_endpoints=True), client_factory=factory))
    r = c.post(
        f"{API}/ab-test",
        json={"base_url": "http://127.0.0.1:8001/v1", "model": "m", "n_requests": 1, "formats": ["xml_schema"]},
    )
    assert r.status_code == 202 and r.json()["warnings"] == []
    assert factory.calls[0][:2] == ("http://127.0.0.1:8001/v1", "m")
    job = wait_done(c, r.json()["job_id"])
    assert job["status"] == "done" and job["result"]["scores"][0]["accuracy"] == 0.0


def test_ab_test_needs_a_model_name():
    c = TestClient(create_app(ServeConfig(endpoint=ENDPOINT), client_factory=Factory("x")))
    r = c.post(f"{API}/ab-test", json={})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_ab_test_bad_inputs():
    c = TestClient(create_app(ServeConfig(endpoint=ENDPOINT, endpoint_model="m"), client_factory=Factory("x")))
    assert c.post(f"{API}/ab-test", json={"formats": ["xml"]}).json()["error"] == "unknown_format"
    r = c.post(f"{API}/ab-test", json={"examples": [{"request": "hi", "calls": []}]})
    assert r.status_code == 400 and "tools" in r.json()["detail"]
    tools = {"source": "openai", "payload": S.EXAMPLE_TOOLS["payload"]}
    assert c.post(f"{API}/ab-test", json={"tools": tools, "examples": []}).status_code == 400
    bad = c.post(f"{API}/ab-test", json={"tools": tools, "examples": [{"request": "hi", "calls": [{"x": 1}]}]})
    assert bad.status_code == 422 and bad.json()["error"] == "validation_error"
    assert c.post(f"{API}/ab-test", json={"n_requests": 0}).json()["error"] == "validation_error"


def test_client_failures_are_counted_not_raised():
    class ExplodingClient:
        model = "m"

        def chat(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("never answers")

    c = TestClient(
        create_app(ServeConfig(endpoint=ENDPOINT, endpoint_model="m"), client_factory=lambda *a: ExplodingClient())
    )
    r = c.post(f"{API}/ab-test", json={"n_requests": 1, "formats": ["xml_schema"]})
    job = wait_done(c, r.json()["job_id"])
    # Regression: a dead endpoint used to finish "done" with a winner. Every request failing fails the job.
    assert job["status"] == "failed" and "every one of the 1 requests failed" in job["error"]
    assert job["result"] is None


def test_unknown_job_404():
    c = TestClient(create_app())
    r = c.get(f"{API}/ab-test/ffff")
    assert r.status_code == 404 and r.json()["error"] == "job_not_found"


# --------------------------------------------------------------------------- #
# the job store itself
# --------------------------------------------------------------------------- #


def _wait(store: JobStore, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job and job["status"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_job_store_progress_and_result():
    store = JobStore(max_workers=1)

    def fn(progress: Any) -> dict[str, Any]:
        for i in range(1, 4):
            progress(i, 3)
        return {"answer": 42}

    job_id = store.submit(fn, total=3)
    assert len(job_id) == 32
    job = _wait(store, job_id)
    assert job["status"] == "done" and job["result"] == {"answer": 42} and job["done"] == 3
    assert set(job) == {"id", "status", "done", "total", "result", "error", "created_at"}
    assert store.list()[0]["id"] == job_id and "result" not in store.list()[0]
    assert store.active() == 0
    store.shutdown(wait=True)


def test_job_store_failure():
    store = JobStore(max_workers=1)

    def fn(progress: Any) -> dict[str, Any]:
        raise ValueError("bad input")

    job = _wait(store, store.submit(fn))
    assert job["status"] == "failed" and job["error"] == "ValueError: bad input" and job["result"] is None
    assert "traceback" not in job
    assert store.get("missing") is None
    store.shutdown()


def test_job_store_prunes_old_finished_jobs():
    store = JobStore(max_workers=1, keep=2)
    ids = []
    for i in range(5):
        job_id = store.submit(lambda progress, i=i: {"i": i})
        _wait(store, job_id)
        ids.append(job_id)
    assert store.get(ids[0]) is None and store.get(ids[-1]) is not None
    store.shutdown()


def test_job_store_needs_a_worker():
    with pytest.raises(ValueError):
        JobStore(max_workers=0)


def test_failed_job_reports_error(monkeypatch):
    import toolform.advisor.measure as measure

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("measurement exploded")

    monkeypatch.setattr(measure, "ab_test", boom)
    c = TestClient(create_app(ServeConfig(endpoint=ENDPOINT, endpoint_model="m"), client_factory=Factory("x")))
    r = c.post(f"{API}/ab-test", json={"n_requests": 1})
    job = wait_done(c, r.json()["job_id"])
    assert job["status"] == "failed" and job["error"] == "RuntimeError: measurement exploded"
    assert job["result"] is None


def test_ab_test_bounds_dedupe_thinking_and_cancel():
    # Regression: 500 formats x 1,000 requests was accepted, the queue had no limit, nothing could
    # cancel a job, and thinking could not be turned off over HTTP.
    import threading

    seen: dict[str, Any] = {}
    gate = threading.Event()

    def factory(base_url: str, model: str, key_env: str | None, *, enable_thinking: bool | None = None) -> Any:
        seen["thinking"] = enable_thinking

        class Slow:
            def __init__(self) -> None:
                self.model = model

            def chat(self, *a: Any, **k: Any) -> Any:
                gate.wait(5)
                raise RuntimeError("slow")

        return Slow()

    c = TestClient(
        create_app(
            ServeConfig(endpoint=ENDPOINT, endpoint_model="Qwen/Qwen3-8B", max_jobs=1, max_ab_requests=100),
            client_factory=factory,
        )
    )
    big = c.post(f"{API}/ab-test", json={"n_requests": 50, "formats": ["xml_schema", "json_minimal", "toml"]})
    assert big.status_code == 413 and "150 requests" in big.json()["detail"]
    many = c.post(f"{API}/ab-test", json={"formats": ["xml_schema"] * 17})
    assert many.status_code == 422
    first = c.post(f"{API}/ab-test", json={"n_requests": 2, "formats": ["xml_schema", "xml_schema"]}).json()
    assert first["total"] == 2 and "repeated formats run once" in first["warnings"]
    assert seen["thinking"] is False and any("thinking is off" in w for w in first["warnings"])
    queued = c.post(f"{API}/ab-test", json={"n_requests": 2, "formats": ["xml_schema"], "thinking": True})
    assert queued.status_code == 202 and seen["thinking"] is True
    full = c.post(f"{API}/ab-test", json={"n_requests": 2, "formats": ["xml_schema"]})
    assert full.status_code == 429 and full.json()["error"] == "too_many_jobs"
    gone = c.delete(f"{API}/ab-test/{queued.json()['job_id']}")
    assert gone.status_code == 200 and gone.json()["status"] == "cancelled"
    running = c.delete(f"{API}/ab-test/{first['job_id']}")
    assert running.status_code == 200
    gate.set()
    assert wait_done(c, first["job_id"])["status"] == "cancelled"
    assert c.delete(f"{API}/ab-test/ffff").status_code == 404
