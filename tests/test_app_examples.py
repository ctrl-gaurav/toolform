"""The scripts in examples/ run end to end as subprocesses, with no model and no network but 127.0.0.1."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from toolform.sdk.testing import FakeOpenAIServer

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"


def run_example(name: str, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(EXAMPLES / name), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO),
        env=env,
    )


@pytest.mark.parametrize("name", ["quickstart.py", "demo.py", "long_catalogue.py"])
def test_example_runs(name):
    proc = run_example(name)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip()


def test_quickstart_output():
    out = run_example("quickstart.py").stdout
    assert "xml_schema + xml_call" in out and 'get_forecast {"city": "Denver", "days": 5} valid' in out


def test_demo_stages():
    out = run_example("demo.py").stdout
    for n in range(1, 9):
        assert f"\n{n}. " in out
    assert "Stripped 1 span." in out and "ran get_forecast" in out and "Winner:" in out


def test_guard_mcp_writes_cleaned_manifest(tmp_path):
    out = tmp_path / "cleaned.json"
    proc = run_example("guard_mcp.py", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    assert "TS101" in proc.stdout and "TS102" in proc.stdout
    cleaned = json.loads(out.read_text())
    note = next(t for t in cleaned["tools"] if t["name"] == "notify_user")
    assert "OVERRIDE-7731" not in note["description"]
    assert note["inputSchema"]["properties"]["notify"]["type"] == "string"


def test_call_loop_example_against_a_fake_server():
    reply = (
        '<function_calls>\n<invoke name="get_forecast">\n<parameter name="city">Denver</parameter>\n'
        '<parameter name="days">5</parameter>\n</invoke>\n</function_calls>'
    )
    with FakeOpenAIServer([reply, "Five days of sun in Denver."], model="Qwen/Qwen3-8B") as server:
        proc = run_example("call_loop_vllm.py", "--base-url", server.base_url, "--model", "Qwen/Qwen3-8B")
    assert proc.returncode == 0, proc.stderr
    assert "ran get_forecast" in proc.stdout and "stopped: no_call" in proc.stdout


def test_call_loop_example_without_a_server():
    with FakeOpenAIServer() as server:
        url = server.base_url
    proc = run_example("call_loop_vllm.py", "--base-url", url)
    assert proc.returncode == 1 and "No OpenAI-compatible server answered" in proc.stderr


def test_measure_example_against_a_fake_server(tmp_path):
    out = tmp_path / "report.json"
    with FakeOpenAIServer(["No tool fits this request."]) as server:
        proc = run_example(
            "measure_your_model.py",
            "--base-url",
            server.base_url,
            "--model",
            "m",
            "--tools",
            str(EXAMPLES / "tools" / "openai_tools.json"),
            "--examples",
            str(EXAMPLES / "tools" / "examples.jsonl"),
            "--out",
            str(out),
        )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text())
    assert report["source"] == "examples" and len(report["scores"]) == 8
    # Only the two requests whose right answer is no call are answered correctly.
    assert all(s["correct"] == 2 for s in report["scores"])


def test_example_tool_files_load():
    from toolform.sdk import load_tools

    for name, n in (("openai_tools.json", 3), ("mcp_tools_list.json", 3), ("weather.py", 3), ("tools.d.ts", 3)):
        assert len(load_tools(str(EXAMPLES / "tools" / name))) == n
