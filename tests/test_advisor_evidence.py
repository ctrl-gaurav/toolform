"""The shipped evidence: files, envelope, hashes, and the numbers the ground rules name."""

from __future__ import annotations

import hashlib
import json
import math

import pytest

from toolform.advisor.evidence import DATA_DIR, EVIDENCE_FILES, Evidence, EvidenceRow, load_evidence
from toolform.sdk import CORE_FORMATS, EvidenceError


def test_every_file_loads_with_envelope_and_hash(evidence):
    manifest = evidence.load("manifest")
    by_name = {f["name"]: f for f in manifest["files"]}
    assert set(by_name) == set(EVIDENCE_FILES) - {"manifest"}
    total = 0
    for name in EVIDENCE_FILES:
        path = DATA_DIR / f"{name}.json"
        data = path.read_bytes()
        total += len(data)
        obj = evidence.load(name)
        if name == "manifest":
            continue
        assert list(obj)[:6] == ["schema_version", "name", "source", "description", "conditions", "data"]
        assert obj["name"] == name and obj["schema_version"] == 1 and obj["source"]
        assert by_name[name]["sha256"] == hashlib.sha256(data).hexdigest()
        assert by_name[name]["bytes"] == len(data)
    assert total < 2 * 1024 * 1024
    assert evidence.version == manifest["evidence_version"] and evidence.files() == manifest["files"]


@pytest.mark.parametrize(
    "fid,value",
    [
        ("schema_over_names", 57.09),
        ("xml_minus_json_main", 13.80),
        ("xml_minus_json_symmetric", 1.07),
        ("xml_minus_json_as_written", -3.28),
        ("protocol_ratio_main", 2.00),
        ("protocol_ratio_symmetric", 1.68),
        ("protocol_ratio_as_written", 1.22),
        ("grammar_hallucinated_free", 1.07),
        ("grammar_hallucinated_fixed", 0.01),
        ("injection_min", 38.48),
        ("injection_max", 54.16),
        ("tool_count_cost", 41.01),
        ("measure_eight", 69.18),
        ("fitted_rule", 64.35),
        ("always_json", 57.97),
        ("n_formats", 129),
        ("n_protocols", 31),
        ("n_rules", 3),
        ("n_open_models", 100),
        ("n_proprietary_models", 12),
        ("n_domains", 24),
        ("n_real_tools", 66),
        ("n_real_requests", 1248),
        ("n_public_benchmarks", 6),
    ],
)
def test_headline_facts(evidence, fid, value):
    assert evidence.fact(fid)["value"] == pytest.approx(value)


def test_fact_shape(evidence):
    for f in evidence.facts():
        assert set(f) == {"id", "value", "interval", "unit", "text", "source", "check"}
        assert f["check"]["file"].startswith("paper/") and f["check"]["contains"]
    assert evidence.fact("schema_over_names")["interval"] == [50.40, 64.02]
    assert evidence.fact_value("measure_eight_requests") == 400
    with pytest.raises(EvidenceError):
        evidence.fact("nope")


def test_core_tables(evidence):
    assert evidence.core_accuracy("xml_schema") == 67.52
    assert evidence.core_accuracy("json_schema_openai") == 53.71
    assert evidence.core_accuracy("json_schema_openai", "symmetric") == 66.44
    assert evidence.core_accuracy("xml_schema", "as_written") == 50.43
    with pytest.raises(EvidenceError):
        evidence.core_accuracy("ascii_table")
    with pytest.raises(EvidenceError):
        evidence.core_accuracy("xml_schema", "loose")
    rows = evidence.load("core_main")["data"]["rows"]
    xml = rows[0]
    assert xml["rank_main"] == 1 and xml["minus_json_main"] == {"value": 13.8, "interval": [9.16, 18.72]}


def test_families(evidence):
    rows = evidence.load("families")["data"]["rows"]
    open_rows = [r for r in rows if r["kind"] == "open"]
    assert len(open_rows) == 16
    assert evidence.family_row("qwen3")["accuracy"]["xml_schema"] == 77.7
    assert evidence.family_row("qwen3")["best_format"] == "xml_schema"
    assert evidence.family_row("claude") is None
    anchor = evidence.anchor_row("Claude Opus 5.5 (medium)")
    assert anchor["effort"] == "medium" and anchor["family"] is None and anchor["kind"] == "anchor_proprietary"
    assert evidence.anchor_row("Qwen 3") is None
    assert all(set(r["accuracy"]) == set(CORE_FORMATS) for r in rows)
    assert any(r["kind"] == "anchor_open" for r in evidence.anchor_rows())


def test_count_interpolation_and_clamping(evidence):
    assert evidence.count_accuracy("xml_schema", 8) == (65.3, False)
    assert evidence.count_accuracy("xml_schema", 256) == (27.8, False)
    v, clamped = evidence.count_accuracy("xml_schema", 12)
    t = (math.log2(12) - 3) / 1
    assert v == pytest.approx(65.3 + t * (60.4 - 65.3)) and not clamped
    assert evidence.count_accuracy("xml_schema", 500) == (27.8, True)
    assert evidence.empty_share("json_schema_openai", 256) == (56.0, False)
    assert evidence.empty_share("xml_schema", 1000)[1]
    with pytest.raises(EvidenceError):
        evidence.count_accuracy("ascii_table", 8)
    with pytest.raises(EvidenceError):
        evidence.empty_share("ascii_table", 8)


def test_other_lookups(evidence):
    assert evidence.tier_accuracy("xml_schema", 3) == 65.6
    assert evidence.tier_accuracy("xml_schema", 9) == 42.4  # nearest measured tier
    with pytest.raises(EvidenceError):
        evidence.tier_accuracy("ascii_table", 3)
    assert evidence.crossing("main", "xml_schema", "xml_call") == 69.8
    assert evidence.crossing("symmetric", "json_schema_openai", "json_object") == 70.2
    assert evidence.crossing("main", "xml_schema", "json_array") is None
    assert evidence.cost_row("json_minimal")["schema"] == 448.1 and evidence.cost_row("ascii_table") is None
    assert evidence.injection_row("markdown_table")["hijack"] == 54.16 and evidence.injection_row("x") is None
    at16 = {r["arm"]: r for r in evidence.disclosure_rows(16)}
    assert at16["names_desc"]["minus_json"] == {"value": 1.88, "interval": [-1.99, 5.32]}
    assert {r["n_tools"] for r in evidence.disclosure_rows(8)} == {16}  # a tie goes to the larger count
    assert {r["n_tools"] for r in evidence.disclosure_rows(1000)} == {256}
    sel = evidence.selection()
    assert sel["mean"]["measure_eight"] == 69.18 and len(sel["rows"]) == 16 and sel["cells"] == 55732


def test_formats_and_protocols(evidence):
    fm = evidence.load("formats")["data"]
    assert len(fm) == 133 and sum(1 for f in fm.values() if f["in_study"]) == 129
    assert sum(1 for f in fm.values() if f["core"]) == 8
    assert evidence.format_meta("xml_schema")["measured"]["source"] == "export:format_leaderboard"
    assert all(f["measured"] is not None for f in fm.values() if f["in_study"])
    with pytest.raises(EvidenceError):
        evidence.format_meta("nope")
    pr = evidence.load("protocols")["data"]
    assert len(pr) == 31 and sum(1 for p in pr.values() if p["in_crossing"]) == 5
    assert evidence.protocol_meta("xml_call")["id"] == "xml_call"
    with pytest.raises(EvidenceError):
        evidence.protocol_meta("nope")


def test_errors_and_cache(tmp_path):
    ev = Evidence(tmp_path)
    with pytest.raises(EvidenceError, match="missing"):
        ev.load("facts")
    with pytest.raises(EvidenceError, match="unknown evidence file"):
        ev.load("secrets")
    (tmp_path / "facts.json").write_text("{bad")
    with pytest.raises(EvidenceError, match="not valid JSON"):
        ev.load("facts")
    assert load_evidence() is load_evidence()
    assert load_evidence(str(DATA_DIR)).version == load_evidence().version


def test_evidence_row():
    r = EvidenceRow(source="paper:tab_main", label="x", value=1.23456, interval=(1.0, 2.0))
    assert r.to_dict() == {
        "source": "paper:tab_main",
        "label": "x",
        "value": 1.2346,
        "unit": "%",
        "interval": [1.0, 2.0],
        "note": "",
    }
    assert EvidenceRow(source="s", label="l", value=None).to_dict()["value"] is None
    json.dumps(r.to_dict())
