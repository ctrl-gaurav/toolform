"""ServeConfig.from_env for every variable."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from toolform.serve import ServeConfig  # noqa: E402
from toolform.serve.config import DEFAULT_CORS, ENV_VARS  # noqa: E402


def test_defaults():
    cfg = ServeConfig.from_env({})
    assert cfg == ServeConfig()
    assert cfg.host == "127.0.0.1" and cfg.port == 8765 and cfg.cors_origins == DEFAULT_CORS
    assert cfg.endpoint is None and cfg.endpoint_model is None and cfg.endpoint_api_key_env == "OPENAI_API_KEY"
    assert cfg.allow_client_endpoints is False and cfg.max_tools == 2000 and cfg.max_text_chars == 1_000_000
    assert cfg.max_jobs == 4 and cfg.endpoint_configured is False


def test_every_variable():
    env = {
        "TOOLFORM_HOST": "0.0.0.0",
        "TOOLFORM_PORT": "9000",
        "TOOLFORM_CORS": "http://a.test, http://b.test,,",
        "TOOLFORM_ENDPOINT": "http://127.0.0.1:8000/v1",
        "TOOLFORM_ENDPOINT_MODEL": "Qwen/Qwen3-8B",
        "TOOLFORM_ENDPOINT_KEY_ENV": "MY_KEY",
        "TOOLFORM_ALLOW_CLIENT_ENDPOINTS": "yes",
        "TOOLFORM_MAX_TOOLS": "10",
        "TOOLFORM_MAX_TEXT_CHARS": "500",
        "TOOLFORM_MAX_BODY_BYTES": "4000",
        "TOOLFORM_MAX_JOBS": "2",
        "TOOLFORM_MAX_AB_REQUESTS": "300",
        "TOOLFORM_ALLOWED_HOSTS": "tools.lan, 10.0.0.5",
    }
    assert set(env) == set(ENV_VARS)
    cfg = ServeConfig.from_env(env)
    assert cfg.host == "0.0.0.0" and cfg.port == 9000
    assert cfg.cors_origins == ("http://a.test", "http://b.test")
    assert cfg.endpoint == "http://127.0.0.1:8000/v1" and cfg.endpoint_model == "Qwen/Qwen3-8B"
    assert cfg.endpoint_api_key_env == "MY_KEY" and cfg.allow_client_endpoints is True
    assert cfg.max_tools == 10 and cfg.max_text_chars == 500 and cfg.max_body_bytes == 4000 and cfg.max_jobs == 2
    assert cfg.endpoint_configured is True and cfg.max_ab_requests == 300
    assert cfg.allowed_hosts == ("tools.lan", "10.0.0.5")
    assert set(cfg.host_names()) == {"localhost", "127.0.0.1", "::1", "tools.lan", "10.0.0.5"}
    for var, name in ENV_VARS.items():
        assert hasattr(cfg, name), var


def test_round_trip_through_env():
    cfg = ServeConfig(
        host="127.0.0.2",
        port=1234,
        cors_origins=("http://x.test",),
        endpoint="http://e/v1",
        endpoint_model="m",
        endpoint_api_key_env=None,
        allow_client_endpoints=True,
        max_tools=3,
        max_text_chars=4,
        max_body_bytes=5,
        max_jobs=6,
    )
    assert ServeConfig.from_env(cfg.to_env()) == cfg
    assert ServeConfig.from_env(ServeConfig().to_env()) == ServeConfig()


def test_empty_values():
    cfg = ServeConfig.from_env({"TOOLFORM_CORS": "", "TOOLFORM_ENDPOINT_KEY_ENV": "", "TOOLFORM_HOST": ""})
    assert cfg.cors_origins == () and cfg.endpoint_api_key_env is None and cfg.host == "127.0.0.1"


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("ON", True), ("0", False), ("false", False), ("off", False), ("no", False)],
)
def test_boolean_spellings(value, expected):
    assert ServeConfig.from_env({"TOOLFORM_ALLOW_CLIENT_ENDPOINTS": value}).allow_client_endpoints is expected


@pytest.mark.parametrize(
    "env",
    [
        {"TOOLFORM_PORT": "http"},
        {"TOOLFORM_PORT": "70000"},
        {"TOOLFORM_MAX_TOOLS": "0"},
        {"TOOLFORM_ALLOW_CLIENT_ENDPOINTS": "maybe"},
        {"TOOLFORM_MAX_JOBS": "-1"},
    ],
)
def test_bad_values_name_the_variable(env):
    with pytest.raises(ValueError) as info:
        ServeConfig.from_env(env)
    assert next(iter(env)) in str(info.value)


def test_to_dict_has_no_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    d = ServeConfig().to_dict()
    assert "sk-secret" not in str(d) and d["endpoint_api_key_env"] == "OPENAI_API_KEY"
    assert isinstance(d["cors_origins"], list)


def test_reads_os_environ(monkeypatch):
    monkeypatch.setenv("TOOLFORM_PORT", "8123")
    assert ServeConfig.from_env().port == 8123


def test_run_starts_uvicorn(monkeypatch):
    import os

    import uvicorn

    from toolform.serve import run

    calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(os, "environ", dict(os.environ))
    run(ServeConfig(port=9123))
    ((args, kwargs),) = calls
    assert kwargs == {"host": "127.0.0.1", "port": 9123}
    assert args[0].title == "ToolForm API"
    calls.clear()
    run(ServeConfig(port=9124, endpoint="http://127.0.0.1:8000/v1"), reload=True)
    ((args, kwargs),) = calls
    assert args == ("toolform.serve.app:create_app_from_env",)
    assert kwargs["factory"] is True and kwargs["reload"] is True and kwargs["port"] == 9124
    assert os.environ["TOOLFORM_PORT"] == "9124" and os.environ["TOOLFORM_ENDPOINT"] == "http://127.0.0.1:8000/v1"


def test_create_app_from_env(monkeypatch):
    from toolform.serve import create_app_from_env

    monkeypatch.setenv("TOOLFORM_MAX_TOOLS", "7")
    monkeypatch.setenv("TOOLFORM_ENDPOINT", "http://127.0.0.1:8000/v1")
    app = create_app_from_env()
    assert app.state.config.max_tools == 7 and app.state.config.endpoint_configured


def test_default_client_factory():
    from toolform.sdk import OpenAICompatClient
    from toolform.serve.app import default_client_factory

    client = default_client_factory("http://127.0.0.1:8000/v1/", "m", None)
    assert isinstance(client, OpenAICompatClient)
    assert client.base_url == "http://127.0.0.1:8000/v1" and client.model == "m" and client.api_key is None
