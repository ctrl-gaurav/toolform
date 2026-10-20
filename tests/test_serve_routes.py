"""Every route of the HTTP API through FastAPI's TestClient: status, keys, models, errors, CORS."""

from __future__ import annotations

import json
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


from toolform.advisor import recommend  # noqa: E402
from toolform.advisor.evidence import EVIDENCE_FILES, load_evidence  # noqa: E402
from toolform.catalogue import plan_catalogue, retrieve  # noqa: E402
from toolform.guard import guard  # noqa: E402
from toolform.sdk import Toolset, parse_reply, render  # noqa: E402
from toolform.sdk.constants import FRAMEWORK_VERSION  # noqa: E402
from toolform.serve import ServeConfig, create_app  # noqa: E402
from toolform.serve import schemas as S  # noqa: E402

API = "/api/v1"
SITE = "https://ctrl-gaurav.github.io"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(ServeConfig()))


@pytest.fixture
def openai_payload(fixtures_dir: Path) -> list[dict[str, Any]]:
    return json.loads((fixtures_dir / "openai_tools.json").read_text())


@pytest.fixture
def mcp_payload(fixtures_dir: Path) -> dict[str, Any]:
    return json.loads((fixtures_dir / "mcp_tools_list.json").read_text())


def tools_obj(payload: Any, source: str = "auto") -> dict[str, Any]:
    return {"source": source, "payload": payload}


def check_model(model: type, body: dict[str, Any]) -> None:
    """The body validates against the model, and carries exactly the model's fields."""
    model.model_validate(body)
    assert set(model.model_fields) == set(body), set(model.model_fields) ^ set(body)


def check_error(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["error"] == code and body["status"] == status and "detail" in body
    S.ErrorBody.model_validate(body)
    return body


# --------------------------------------------------------------------------- #
# meta and registry
# --------------------------------------------------------------------------- #


def test_health(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    check_model(S.HealthResponse, body)
    assert body == {
        "status": "ok",
        "version": FRAMEWORK_VERSION,
        "evidence_version": load_evidence().version,
        "endpoint_configured": False,
        "allow_client_endpoints": False,
    }


def test_health_reports_endpoint():
    c = TestClient(create_app(ServeConfig(endpoint="http://127.0.0.1:9/v1", allow_client_endpoints=True)))
    body = c.get(f"{API}/health").json()
    assert body["endpoint_configured"] is True and body["allow_client_endpoints"] is True


def test_version(client):
    body = client.get(f"{API}/version").json()
    check_model(S.VersionResponse, body)
    assert body["framework"] == FRAMEWORK_VERSION and "research_harness" not in body
    assert body["evidence"] == load_evidence().version


def test_root_points_to_docs(client):
    body = client.get("/").json()
    assert body["docs"] == "/docs" and body["api"] == API


def test_formats(client):
    body = client.get(f"{API}/formats").json()
    check_model(S.FormatsResponse, body)
    assert body["count_registered"] == 133 and body["count_in_study"] == 129
    assert len(body["formats"]) == 133
    core = client.get(f"{API}/formats", params={"core": "true"}).json()["formats"]
    assert sorted(f["id"] for f in core) == sorted(
        [
            "xml_schema",
            "natural_language",
            "python_stub",
            "json_schema_openai",
            "yaml_schema",
            "typescript",
            "markdown_table",
            "json_minimal",
        ]
    )
    fam = client.get(f"{API}/formats", params={"family": "json"}).json()["formats"]
    assert fam and all(f["family"] == "json" for f in fam)
    study = client.get(f"{API}/formats", params={"in_study": "true"}).json()["formats"]
    assert len(study) == 129


def test_format_detail(client):
    body = client.get(f"{API}/formats/xml_schema").json()
    S.FormatDetail.model_validate(body)
    assert (
        body["id"] == "xml_schema" and "<tool>" in body["sample"]["text"] or "legal_draft_v3" in body["sample"]["text"]
    )
    assert body["sample"]["tokens_estimate"] >= 1 and body["sample"]["instructions"]


def test_format_detail_two_stage(client):
    body = client.get(f"{API}/formats/names_then_schema").json()
    assert "note" in body["sample"]


def test_unknown_format_404_with_close_matches(client):
    body = check_error(client.get(f"{API}/formats/xml_schem"), 404, "unknown_format")
    assert "xml_schema" in body["detail"]


def test_protocols(client):
    body = client.get(f"{API}/protocols").json()
    check_model(S.ProtocolsResponse, body)
    assert len(body["protocols"]) == 31


def test_models(client):
    body = client.get(f"{API}/models").json()
    assert body == load_evidence().load("zoo")["data"]
    assert len(body["models"]) == 100


def test_unknown_route_uses_error_shape(client):
    check_error(client.get(f"{API}/nope"), 404, "not_found")


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


def test_tools_load(client, openai_payload):
    r = client.post(f"{API}/tools/load", json={"tools": tools_obj(openai_payload)})
    assert r.status_code == 200, r.text
    body = r.json()
    check_model(S.ToolsLoadResponse, body)
    ts = Toolset.from_openai(openai_payload)
    assert body["kind"] == "openai" and body["summary"] == ts.summary() and body["tools"] == ts.to_ir()["tools"]


def test_tools_load_every_http_kind(client, fixtures_dir):
    for name, source in (
        ("anthropic_tools.json", "anthropic"),
        ("mcp_tools_list.json", "mcp"),
        ("mcp_jsonrpc.json", "auto"),
        ("ir_tools.json", "ir"),
    ):
        payload = json.loads((fixtures_dir / name).read_text())
        r = client.post(f"{API}/tools/load", json={"tools": tools_obj(payload, source)})
        assert r.status_code == 200, (name, r.text)
        assert r.json()["summary"]["n_tools"] >= 1


def test_tools_load_json_text_payload(client, openai_payload):
    r = client.post(f"{API}/tools/load", json={"tools": tools_obj(json.dumps(openai_payload))})
    assert r.status_code == 200 and r.json()["kind"] == "openai"


def test_tools_load_typescript_text(client, fixtures_dir):
    src = (fixtures_dir / "tools.d.ts").read_text()
    for source in ("typescript", "auto"):
        r = client.post(f"{API}/tools/load", json={"tools": tools_obj(src, source)})
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "typescript"
        assert "open_ticket" in r.json()["summary"]["names"]


def test_string_payload_is_never_a_path(client, fixtures_dir):
    # A file name sent as text must not be read from the server's disk.
    path = str(fixtures_dir / "tools.d.ts")
    r = client.post(f"{API}/tools/load", json={"tools": tools_obj(path, "typescript")})
    assert r.status_code == 422
    r = client.post(f"{API}/tools/load", json={"tools": tools_obj(str(fixtures_dir / "pytools.py"), "auto")})
    assert r.status_code == 422
    r = client.post(f"{API}/tools/load", json={"tools": tools_obj(str(fixtures_dir / "openai_tools.json"), "openai")})
    check_error(r, 400, "bad_request")


def test_python_source_refused(client):
    body = check_error(
        client.post(f"{API}/tools/load", json={"tools": tools_obj("def f(): pass", "python")}), 400, "bad_request"
    )
    assert "python" in body["detail"]


def test_unknown_source_refused(client, openai_payload):
    check_error(client.post(f"{API}/tools/load", json={"tools": tools_obj(openai_payload, "yaml")}), 400, "bad_request")


def test_typescript_needs_text(client, openai_payload):
    check_error(
        client.post(f"{API}/tools/load", json={"tools": tools_obj(openai_payload, "typescript")}), 400, "bad_request"
    )


def test_bad_payload_types(client):
    check_error(client.post(f"{API}/tools/load", json={"tools": {"source": "auto", "payload": 3}}), 400, "bad_request")
    check_error(
        client.post(f"{API}/tools/load", json={"tools": {"source": "auto", "payload": None}}), 400, "bad_request"
    )


def test_loader_error_422(client, fixtures_dir):
    bad = json.loads((fixtures_dir / "bad_tools.json").read_text())
    payload = bad if not isinstance(bad, dict) or "tools" in bad else bad
    r = client.post(f"{API}/tools/load", json={"tools": tools_obj(payload, "openai")})
    check_error(r, 422, "loader_error")


def test_loader_error_line_for_bad_json_text(client):
    body = check_error(client.post(f"{API}/tools/load", json={"tools": tools_obj('[\n{"a": ,}]')}), 422, "loader_error")
    assert body["line"] == 2


def test_loader_error_line_for_typescript(client):
    r = client.post(f"{API}/tools/load", json={"tools": tools_obj("// nothing here\nconst x = 1;\n", "typescript")})
    check_error(r, 422, "loader_error")


def test_validation_error_shape(client):
    body = check_error(client.post(f"{API}/tools/load", json={"nope": 1}), 422, "validation_error")
    assert isinstance(body["detail"], list) and body["detail"]


def test_tools_export(client, openai_payload):
    ts = Toolset.from_openai(openai_payload)
    for to, expected in (
        ("openai", ts.to_openai()),
        ("anthropic", ts.to_anthropic()),
        ("mcp", ts.to_mcp()),
        ("ir", ts.to_ir()),
    ):
        r = client.post(f"{API}/tools/export", json={"tools": tools_obj(openai_payload), "to": to})
        assert r.status_code == 200
        body = r.json()
        check_model(S.ToolsExportResponse, body)
        assert body == {"to": to, "payload": json.loads(json.dumps(expected))}


def test_too_many_tools_413():
    c = TestClient(create_app(ServeConfig(max_tools=2)))
    payload = [
        {"type": "function", "function": {"name": f"t{i}", "parameters": {"type": "object", "properties": {}}}}
        for i in range(3)
    ]
    body = check_error(c.post(f"{API}/tools/load", json={"tools": tools_obj(payload)}), 413, "payload_too_large")
    assert "limit is 2" in body["detail"]


def test_too_many_typescript_tools_413(fixtures_dir):
    c = TestClient(create_app(ServeConfig(max_tools=1)))
    src = (fixtures_dir / "tools.d.ts").read_text()
    check_error(c.post(f"{API}/tools/load", json={"tools": tools_obj(src, "typescript")}), 413, "payload_too_large")


def test_too_much_text_413(openai_payload):
    c = TestClient(create_app(ServeConfig(max_text_chars=50)))
    r = c.post(f"{API}/parse", json={"tools": tools_obj(openai_payload), "text": "x" * 51, "protocol": "json_object"})
    check_error(r, 413, "payload_too_large")


def test_body_limit_413_declared_length(openai_payload):
    c = TestClient(create_app(ServeConfig(max_body_bytes=100)))
    body = check_error(c.post(f"{API}/tools/load", json={"tools": tools_obj(openai_payload)}), 413, "payload_too_large")
    assert "limit is 100" in body["detail"]


def test_body_limit_413_streamed(openai_payload):
    c = TestClient(create_app(ServeConfig(max_body_bytes=100)))
    data = json.dumps({"tools": tools_obj(openai_payload)}).encode()

    def chunks():
        for i in range(0, len(data), 64):
            yield data[i : i + 64]

    r = c.post(f"{API}/tools/load", content=chunks(), headers={"content-type": "application/json"})
    check_error(r, 413, "payload_too_large")


def test_streamed_body_under_limit_is_replayed(openai_payload):
    c = TestClient(create_app(ServeConfig()))
    data = json.dumps({"tools": tools_obj(openai_payload)}).encode()

    def chunks():
        for i in range(0, len(data), 64):
            yield data[i : i + 64]

    r = c.post(f"{API}/tools/load", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.json()["summary"]["n_tools"] == 3


# --------------------------------------------------------------------------- #
# advisor
# --------------------------------------------------------------------------- #


def test_recommend_matches_sdk(client):
    r = client.post(f"{API}/recommend", json={"situation": {"model": "Qwen/Qwen3-8B", "n_tools": 8, "tier": 3}})
    assert r.status_code == 200, r.text
    body = r.json()
    check_model(S.RecommendationModel, body)
    assert body == json.loads(json.dumps(recommend(model="Qwen/Qwen3-8B", n_tools=8, tier=3).to_dict()))


def test_recommend_reproduces_advisor_cases(client):
    cases = load_evidence().load("advisor_cases")["data"]["cases"]
    for case in cases[:40]:
        r = client.post(f"{API}/recommend", json={"situation": case["situation"]})
        assert r.status_code == 200, r.text
        body = r.json()
        exp = case["expected"]
        assert body["format_id"] == exp["format_id"] and body["protocol_id"] == exp["protocol_id"]
        assert body["expected_accuracy"] == exp["expected_accuracy"]


def test_recommend_empty_body_uses_defaults(client):
    r = client.post(f"{API}/recommend", json={})
    assert r.status_code == 200 and r.json()["situation"]["n_tools"] == 8


def test_recommend_takes_count_and_tier_from_tools(client, openai_payload):
    ts = Toolset.from_openai(openai_payload)
    body = client.post(
        f"{API}/recommend", json={"situation": {"model": "Qwen/Qwen3-8B"}, "tools": tools_obj(openai_payload)}
    ).json()
    assert body["situation"]["n_tools"] == len(ts) and body["situation"]["tier"] == ts.tier_estimate()
    assert body["tokens_source"] == "rendered"
    given = client.post(
        f"{API}/recommend",
        json={"situation": {"model": "Qwen/Qwen3-8B", "n_tools": 40, "tier": 2}, "tools": tools_obj(openai_payload)},
    ).json()
    assert given["situation"]["n_tools"] == 40 and given["situation"]["tier"] == 2


def test_recommend_bad_values(client):
    check_error(client.post(f"{API}/recommend", json={"situation": {"n_tools": 0}}), 422, "validation_error")
    check_error(client.post(f"{API}/recommend", json={"situation": {"rule": "loose"}}), 422, "validation_error")
    check_error(client.post(f"{API}/recommend", json={"situation": {"protocol": "no_such"}}), 400, "bad_request")
    check_error(client.post(f"{API}/recommend", json={"situation": {"candidates": ["nope"]}}), 400, "bad_request")


# --------------------------------------------------------------------------- #
# render and parse
# --------------------------------------------------------------------------- #


def test_render_matches_sdk(client, openai_payload):
    req = {
        "tools": tools_obj(openai_payload),
        "format": "xml_schema",
        "request": "Weather in Paris?",
        "options": {"minify": True},
        "persona": "terse",
        "null_clause": False,
        "trust_line": True,
    }
    r = client.post(f"{API}/render", json=req)
    assert r.status_code == 200, r.text
    body = r.json()
    check_model(S.RenderedPromptModel, body)
    from toolform.sdk import render_options

    ts = Toolset.from_openai(openai_payload)
    expected = render(
        ts,
        "xml_schema",
        options=render_options(minify=True),
        request="Weather in Paris?",
        persona="terse",
        null_clause=False,
        trust_line=True,
    ).to_dict()
    assert body == json.loads(json.dumps(expected))
    assert body["protocol_id"] == "xml_call" and body["messages"][-1]["content"] == "Weather in Paris?"


def test_render_without_request_has_no_messages(client, openai_payload):
    body = client.post(
        f"{API}/render", json={"tools": tools_obj(openai_payload), "format": "yaml_schema", "protocol": "json_object"}
    ).json()
    assert body["messages"] is None and body["protocol_id"] == "json_object"


def test_render_errors(client, openai_payload):
    check_error(
        client.post(f"{API}/render", json={"tools": tools_obj(openai_payload), "format": "xml"}), 404, "unknown_format"
    )
    check_error(
        client.post(
            f"{API}/render", json={"tools": tools_obj(openai_payload), "format": "xml_schema", "protocol": "xml"}
        ),
        404,
        "unknown_protocol",
    )
    body = check_error(
        client.post(f"{API}/render", json={"tools": tools_obj(openai_payload), "format": "names_then_schema"}),
        400,
        "bad_request",
    )
    assert "two-stage" in body["detail"]


def test_render_compare(client, openai_payload):
    r = client.post(
        f"{API}/render/compare",
        json={"tools": tools_obj(openai_payload), "formats": ["xml_schema", "json_schema_openai", "json_minimal"]},
    )
    body = r.json()
    check_model(S.CompareResponse, body)
    assert [row["format_id"] for row in body["rows"]][0] == "json_minimal"
    for row in body["rows"]:
        check_model(S.CompareRow, row)


def test_render_compare_all_study_formats(client, openai_payload):
    rows = client.post(f"{API}/render/compare", json={"tools": tools_obj(openai_payload)}).json()["rows"]
    assert len(rows) == 129
    tokens = [r["tokens_estimate"] for r in rows if r["tokens_estimate"] is not None]
    assert tokens == sorted(tokens)


XML_REPLY = S.EXAMPLE_XML_REPLY


def test_parse_matches_sdk(client):
    payload = S.EXAMPLE_TOOLS["payload"]
    r = client.post(f"{API}/parse", json={"tools": tools_obj(payload), "text": XML_REPLY, "protocol": "xml_call"})
    assert r.status_code == 200, r.text
    body = r.json()
    check_model(S.ParsedReplyModel, body)
    for c in body["calls"]:
        check_model(S.ParsedCallModel, c)
    ts = Toolset.from_openai(payload)
    assert body == json.loads(json.dumps(parse_reply(XML_REPLY, ts, "xml_call").to_dict()))
    assert body["ok"] and body["calls"][0]["arguments"] == {"city": "Denver", "days": 5}


def test_parse_options_and_rules(client):
    payload = S.EXAMPLE_TOOLS["payload"]
    text = '<tool_call>{"name": "get_forecast", "arguments": {"city": "Oslo"}}</tool_call>'
    strict = client.post(
        f"{API}/parse", json={"tools": tools_obj(payload), "text": text, "protocol": "json_object", "rule": "symmetric"}
    ).json()
    lenient = client.post(
        f"{API}/parse",
        json={
            "tools": tools_obj(payload),
            "text": text,
            "protocol": "xml_call",
            "lenient_fallback": True,
            "validate": False,
        },
    ).json()
    assert strict["rule"] == "symmetric"
    assert lenient["calls"] and lenient["calls"][0]["repairs"][0].startswith("lenient:")
    check_error(
        client.post(
            f"{API}/parse",
            json={
                "tools": tools_obj(payload),
                "text": text,
                "protocol": "xml_call",
                "rule": "as_written",
                "lenient_fallback": True,
            },
        ),
        400,
        "bad_request",
    )


def test_parse_unknown_protocol(client):
    check_error(
        client.post(
            f"{API}/parse", json={"tools": tools_obj(S.EXAMPLE_TOOLS["payload"]), "text": "x", "protocol": "nope"}
        ),
        404,
        "unknown_protocol",
    )


def test_parse_hallucinated_tool(client):
    body = client.post(
        f"{API}/parse",
        json={
            "tools": tools_obj(S.EXAMPLE_TOOLS["payload"]),
            "protocol": "json_object",
            "text": '{"name": "launch_rocket", "arguments": {}}',
        },
    ).json()
    assert body["hallucinated"] == ["launch_rocket"] and body["rejected"][0]["reason"] == "unknown tool"
    assert body["ok"] is False


# --------------------------------------------------------------------------- #
# guard
# --------------------------------------------------------------------------- #


def test_guard_strip(client, mcp_payload):
    assert client.post(f"{API}/guard", json={"tools": tools_obj(mcp_payload, "mcp")}).json()["action"] == "report"
    r = client.post(f"{API}/guard", json={"tools": tools_obj(mcp_payload, "mcp"), "action": "strip"})
    assert r.status_code == 200, r.text
    body = r.json()
    S.GuardReportModel.model_validate(body)
    for f in body["findings"]:
        check_model(S.FindingModel, f)
    ts = Toolset.from_mcp(mcp_payload)
    expected = guard(ts, strictness="standard", action="strip").to_dict()
    assert {k: v for k, v in body.items() if k != "cleaned"} == json.loads(json.dumps(expected))
    assert {f["rule_id"] for f in body["findings"]} >= {"TS101", "TS102"}
    assert body["flagged_tools"] == ["notify_user"]
    cleaned = body["cleaned"]
    assert cleaned["kind"] == "mcp"
    desc = next(t for t in cleaned["payload"]["tools"] if t["name"] == "notify_user")["description"]
    assert "OVERRIDE-7731" not in desc and "Send a short notification" in desc


def test_guard_report_and_drop(client, mcp_payload):
    rep = client.post(f"{API}/guard", json={"tools": tools_obj(mcp_payload), "action": "report"}).json()
    assert rep["action"] == "report" and rep["removed"] == []
    drop = client.post(
        f"{API}/guard",
        json={"tools": tools_obj(mcp_payload), "action": "drop-descriptions", "scope": "all", "strictness": "strict"},
    ).json()
    assert drop["action"] == "drop_descriptions" and drop["removed"]
    assert all(not t.get("description") for t in drop["cleaned"]["payload"]["tools"])


def test_guard_typescript_cleaned_as_openai(client, fixtures_dir):
    src = (fixtures_dir / "tools.d.ts").read_text()
    body = client.post(f"{API}/guard", json={"tools": tools_obj(src, "typescript")}).json()
    assert body["cleaned"]["kind"] == "openai"


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #


def test_catalogue_plan(client, openai_payload):
    req = {
        "tools": tools_obj(openai_payload),
        "format": "xml_schema",
        "context_tokens": 100,
        "query": "weather in Paris",
        "k": 2,
    }
    r = client.post(f"{API}/catalogue/plan", json=req)
    assert r.status_code == 200, r.text
    body = r.json()
    check_model(S.CataloguePlanModel, body)
    ts = Toolset.from_openai(openai_payload)
    expected = plan_catalogue(ts, format_id="xml_schema", context_tokens=100, query="weather in Paris", k=2)
    assert body == json.loads(json.dumps(expected.to_dict()))
    assert body["strategy"] == "two_stage" and body["selection_messages"]


def test_catalogue_plan_defaults(client, openai_payload):
    body = client.post(f"{API}/catalogue/plan", json={"tools": tools_obj(openai_payload)}).json()
    assert body["strategy"] == "one_shot" and body["retrieval"] is None


def test_catalogue_retrieve(client, openai_payload):
    r = client.post(
        f"{API}/catalogue/retrieve", json={"tools": tools_obj(openai_payload), "query": "calendar event", "k": 1}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    check_model(S.RetrievalModel, body)
    ts = Toolset.from_openai(openai_payload)
    exp = retrieve(ts, "calendar event", k=1)
    assert body["selected"] == exp.toolset.names() == ["create_event"]
    assert [t["name"] for t in body["tools"]] == ["create_event"]
    keep = client.post(
        f"{API}/catalogue/retrieve",
        json={"tools": tools_obj(openai_payload), "query": "calendar event", "k": 1, "keep": ["get_weather"]},
    ).json()
    assert set(keep["selected"]) == {"get_weather"}
    check_error(
        client.post(
            f"{API}/catalogue/retrieve", json={"tools": tools_obj(openai_payload), "query": "x", "keep": ["nope"]}
        ),
        400,
        "bad_request",
    )


def test_two_stage_prompt(client, openai_payload):
    r = client.post(
        f"{API}/catalogue/two-stage/prompt", json={"tools": tools_obj(openai_payload), "request": "Weather in Rome?"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    check_model(S.TwoStagePromptResponse, body)
    from toolform.catalogue import SELECTION_ASK

    assert body["messages"][-1]["content"].endswith(SELECTION_ASK)
    assert body["selection_format"] == "names_desc_then_schema" and body["tokens_estimate"] > 0
    names_only = client.post(
        f"{API}/catalogue/two-stage/prompt",
        json={"tools": tools_obj(openai_payload), "request": "x", "include_descriptions": False},
    ).json()
    assert names_only["selection_format"] == "names_then_schema_v2"


# --------------------------------------------------------------------------- #
# evidence
# --------------------------------------------------------------------------- #


def test_evidence_manifest(client):
    body = client.get(f"{API}/evidence").json()
    assert body == load_evidence().load("manifest")


@pytest.mark.parametrize("name", EVIDENCE_FILES)
def test_evidence_file(client, name):
    r = client.get(f"{API}/evidence/{name}")
    assert r.status_code == 200
    assert r.json() == load_evidence().load(name)


def test_evidence_unknown(client):
    check_error(client.get(f"{API}/evidence/nope"), 404, "not_found")


def test_facts(client):
    body = client.get(f"{API}/facts").json()
    check_model(S.FactsResponse, body)
    values = {f["id"]: f["value"] for f in body["facts"]}
    assert values["measure_eight"] == 69.18 and values["schema_over_names"] == 57.09


# --------------------------------------------------------------------------- #
# CORS and private network access
# --------------------------------------------------------------------------- #


def test_cors_allowed_origin(client):
    r = client.get(f"{API}/health", headers={"Origin": SITE})
    assert r.headers.get("access-control-allow-origin") == SITE


def test_cors_other_origin(client):
    r = client.get(f"{API}/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers


def test_preflight_private_network(client):
    headers = {
        "Origin": SITE,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
        "Access-Control-Request-Private-Network": "true",
    }
    r = client.options(f"{API}/recommend", headers=headers)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == SITE
    assert r.headers.get("access-control-allow-private-network") == "true"


def test_preflight_private_network_other_origin(client):
    headers = {
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true",
    }
    r = client.options(f"{API}/recommend", headers=headers)
    # The preflight is refused: no allowed origin comes back, so the browser blocks the call.
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_custom_cors_origin():
    c = TestClient(create_app(ServeConfig(cors_origins=("http://localhost:3000",))))
    r = c.get(f"{API}/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    r = c.get(f"{API}/health", headers={"Origin": SITE})
    assert "access-control-allow-origin" not in r.headers


def test_cors_on_error_responses(client):
    r = client.get(f"{API}/formats/nope", headers={"Origin": SITE})
    assert r.status_code == 404 and r.headers.get("access-control-allow-origin") == SITE


# --------------------------------------------------------------------------- #
# error mapping
# --------------------------------------------------------------------------- #


def test_internal_error_shape(monkeypatch):
    import toolform.advisor as advisor_pkg

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(advisor_pkg, "recommend", boom)
    c = TestClient(create_app(), raise_server_exceptions=False)
    body = check_error(c.post(f"{API}/recommend", json={}), 500, "internal_error")
    # Regression: the 500 body carried the exception text; it now says only where to look.
    assert "kaboom" not in body["detail"] and "server log" in body["detail"]
    monkeypatch.setenv("TOOLFORM_DEBUG", "1")
    assert "kaboom" in c.post(f"{API}/recommend", json={}).json()["detail"]


def test_host_header_must_be_local():
    # Regression: any Host was answered, so a DNS-rebinding page could reach the API.
    c = _TestClient(create_app(), base_url="http://attacker.example")
    r = c.get(f"{API}/health")
    assert r.status_code == 421 and r.json()["error"] == "misdirected_request"
    for host in ("localhost", "127.0.0.1", "[::1]"):
        assert _TestClient(create_app(), base_url=f"http://{host}:8765").get(f"{API}/health").status_code == 200
    assert (
        _TestClient(create_app(ServeConfig(allowed_hosts=("tools.lan",))), base_url="http://tools.lan")
        .get(f"{API}/health")
        .status_code
        == 200
    )
    assert (
        _TestClient(create_app(ServeConfig(allowed_hosts=("*",))), base_url="http://anything.test")
        .get(f"{API}/health")
        .status_code
        == 200
    )


def test_malformed_content_length_is_refused():
    c = TestClient(create_app())
    r = c.post(f"{API}/recommend", content=b"{}", headers={"content-length": "abc", "content-type": "application/json"})
    assert r.status_code == 400 and "Content-Length" in r.json()["detail"]


def test_client_error_maps_to_502(monkeypatch):
    import toolform.advisor as advisor_pkg
    from toolform.sdk.errors import ClientError, EvidenceError

    def endpoint_down(*a: Any, **k: Any) -> Any:
        raise ClientError("the endpoint did not answer", status=503)

    monkeypatch.setattr(advisor_pkg, "recommend", endpoint_down)
    c = TestClient(create_app())
    check_error(c.post(f"{API}/recommend", json={}), 502, "endpoint_error")

    def no_evidence(*a: Any, **k: Any) -> Any:
        raise EvidenceError("evidence file missing")

    monkeypatch.setattr(advisor_pkg, "recommend", no_evidence)
    check_error(c.post(f"{API}/recommend", json={}), 404, "not_found")


def test_method_not_allowed_shape(client):
    check_error(client.delete(f"{API}/health"), 405, "method_not_allowed")


def test_unknown_request_keys_are_refused(client: TestClient) -> None:
    """A field at the wrong level is an error, not pooled advice given in silence."""
    r = client.post(f"{API}/recommend", json={"model": "Qwen/Qwen3-8B", "n_tools": 8})
    assert r.status_code == 422 and r.json()["error"] == "validation_error"
    ok = client.post(f"{API}/recommend", json={"situation": {"model": "Qwen/Qwen3-8B", "n_tools": 8, "tier": 3}})
    assert ok.status_code == 200 and ok.json()["basis"] == "checkpoint:Qwen/Qwen3-8B"


def test_infinite_or_nan_params_are_refused(client):
    # Regression: {"params_b": Infinity} returned a surface of 100.0.
    for bad in ("Infinity", "NaN", "1e999"):
        r = client.post(
            f"{API}/recommend",
            content='{"situation": {"params_b": %s}}' % bad,  # noqa: UP031
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 422, (bad, r.text)
    big = client.post(f"{API}/recommend", json={"situation": {"params_b": 5000}}).json()
    assert big["surface"] is None and any("outside the open checkpoints" in w for w in big["warnings"])


def test_empty_tools_are_refused_on_every_tools_route(client):
    # Regression: an empty list was answered with 200 on /recommend, /render and the catalogue routes.
    empty = {"source": "openai", "payload": []}
    for path, body in (
        ("/recommend", {"tools": empty}),
        ("/render", {"tools": empty, "format": "xml_schema"}),
        ("/catalogue/plan", {"tools": empty}),
        ("/catalogue/two-stage/prompt", {"tools": empty, "request": "hi"}),
    ):
        r = client.post(f"{API}{path}", json=body)
        assert r.status_code == 422 and r.json()["error"] == "loader_error", (path, r.text)
