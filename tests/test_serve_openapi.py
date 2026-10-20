"""The OpenAPI document lists every route with its tag, and every request body has an example."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient as _TestClient  # noqa: E402


def TestClient(app, **kw):  # noqa: N802 - a drop-in for fastapi's TestClient
    """The server answers only to local host names, so tests call it as localhost."""
    kw.setdefault("base_url", "http://localhost")
    return _TestClient(app, **kw)


from toolform.sdk.constants import FRAMEWORK_VERSION  # noqa: E402
from toolform.serve import create_app  # noqa: E402
from toolform.serve import schemas as S  # noqa: E402

ROUTES = {
    ("get", "/api/v1/health"): "meta",
    ("get", "/api/v1/version"): "meta",
    ("get", "/api/v1/formats"): "registry",
    ("get", "/api/v1/formats/{format_id}"): "registry",
    ("get", "/api/v1/protocols"): "registry",
    ("get", "/api/v1/models"): "registry",
    ("post", "/api/v1/tools/load"): "tools",
    ("post", "/api/v1/tools/export"): "tools",
    ("post", "/api/v1/recommend"): "advisor",
    ("post", "/api/v1/render"): "render",
    ("post", "/api/v1/render/compare"): "render",
    ("post", "/api/v1/parse"): "parse",
    ("post", "/api/v1/guard"): "guard",
    ("post", "/api/v1/catalogue/plan"): "catalogue",
    ("post", "/api/v1/catalogue/retrieve"): "catalogue",
    ("post", "/api/v1/catalogue/two-stage/prompt"): "catalogue",
    ("post", "/api/v1/ab-test"): "measure",
    ("get", "/api/v1/ab-test/{job_id}"): "measure",
    ("delete", "/api/v1/ab-test/{job_id}"): "measure",
    ("get", "/api/v1/evidence"): "evidence",
    ("get", "/api/v1/evidence/{name}"): "evidence",
    ("get", "/api/v1/facts"): "evidence",
}


@pytest.fixture(scope="module")
def spec() -> dict:
    return TestClient(create_app()).get("/openapi.json").json()


def test_info(spec):
    assert spec["info"]["title"] == "ToolForm API" and spec["info"]["version"] == FRAMEWORK_VERSION
    assert spec["info"]["description"].startswith("ToolForm is an open-source framework")
    assert {t["name"] for t in spec["tags"]} == set(ROUTES.values())


def test_every_route_with_its_tag(spec):
    found = {(m, p): op["tags"] for p, ops in spec["paths"].items() for m, op in ops.items()}
    assert set(found) == set(ROUTES)
    for key, tag in ROUTES.items():
        assert found[key] == [tag], key


def test_every_route_documented(spec):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert op.get("summary") and op.get("description"), (method, path)


def _resolve(spec: dict, schema: dict) -> dict:
    ref = schema.get("$ref")
    if ref:
        return spec["components"]["schemas"][ref.rsplit("/", 1)[1]]
    return schema


def test_every_request_body_has_an_example(spec):
    bodies = 0
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if "requestBody" not in op:
                continue
            bodies += 1
            schema = _resolve(spec, op["requestBody"]["content"]["application/json"]["schema"])
            assert schema.get("examples"), (method, path)
    assert bodies == len(S.REQUEST_MODELS)


def test_request_examples_are_valid():
    for model in S.REQUEST_MODELS:
        examples = model.model_json_schema().get("examples")
        assert examples, model.__name__
        for ex in examples:
            model.model_validate(ex)


def test_request_examples_work_against_the_app():
    client = TestClient(create_app())
    paths = {
        S.ToolsLoadRequest: "/api/v1/tools/load",
        S.ToolsExportRequest: "/api/v1/tools/export",
        S.RecommendRequest: "/api/v1/recommend",
        S.RenderRequest: "/api/v1/render",
        S.CompareRequest: "/api/v1/render/compare",
        S.ParseRequest: "/api/v1/parse",
        S.GuardRequest: "/api/v1/guard",
        S.CataloguePlanRequest: "/api/v1/catalogue/plan",
        S.RetrieveRequest: "/api/v1/catalogue/retrieve",
        S.TwoStagePromptRequest: "/api/v1/catalogue/two-stage/prompt",
    }
    for model, path in paths.items():
        example = model.model_json_schema()["examples"][0]
        r = client.post(path, json=example)
        assert r.status_code == 200, (path, r.text)


def test_errors_documented(spec):
    op = spec["paths"]["/api/v1/ab-test"]["post"]
    assert "409" in op["responses"] and "202" in op["responses"]
    assert "ErrorBody" in spec["components"]["schemas"]


def test_docs_pages_served():
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
