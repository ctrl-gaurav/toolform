---
title: Deploy the API
order: 48
section: Guides
summary: Run toolform serve, configure it with environment variables, put it behind a proxy, and keep ab-test safe.
---

# Deploy the API

`toolform serve` runs the HTTP API behind the dashboard: the advisor, rendering,
parsing, the guard, the catalogue, the evidence and background measurement jobs, all
under `/api/v1`. It needs the `serve` extra (FastAPI, uvicorn and pydantic).

## Start it

```bash
git clone https://github.com/ctrl-gaurav/toolform && pip install -e "./toolform[serve]"
toolform serve
```

```
ToolForm API on http://127.0.0.1:8765 (docs at /docs, OpenAPI at /openapi.json)
```

Without the extra, `toolform serve` prints the install line and exits with code 3.
`python -m toolform.serve` starts the same server.

The OpenAPI schema is at `/openapi.json`, the Swagger UI at `/docs` and ReDoc at
`/redoc`. Every request body there carries a worked example. The [HTTP API
reference](../reference/http-api.md) lists every route.

`/docs` and `/redoc` load their JavaScript from a CDN (`cdn.jsdelivr.net`), as FastAPI
does, so on a machine with no internet access those two pages are blank. The API itself
and `/openapi.json` work offline.

## Options and environment variables

Every option has an environment variable, read by `ServeConfig.from_env()`. A command
line option wins over the variable.

| option | variable | default | meaning |
|---|---|---|---|
| `--host` | `TOOLFORM_HOST` | `127.0.0.1` | address to bind |
| `--port` | `TOOLFORM_PORT` | `8765` | port |
| `--cors ORIGIN ...` | `TOOLFORM_CORS` | the public site and the local development addresses | allowed browser origins; the variable takes a comma-separated list |
| `--endpoint URL` | `TOOLFORM_ENDPOINT` | none | OpenAI-compatible base URL used by `ab-test` |
| `--endpoint-model ID` | `TOOLFORM_ENDPOINT_MODEL` | none | model name sent to that endpoint |
| `--endpoint-key-env ENV` | `TOOLFORM_ENDPOINT_KEY_ENV` | `OPENAI_API_KEY` | name of the variable that holds the endpoint's key |
| `--allow-client-endpoints` | `TOOLFORM_ALLOW_CLIENT_ENDPOINTS` | off | let a request name its own `base_url` |
| `--allowed-host NAME ...` | `TOOLFORM_ALLOWED_HOSTS` | none | host names the server answers to besides `localhost`, `127.0.0.1`, `::1` and `--host`; `*` turns the check off |
| | `TOOLFORM_MAX_TOOLS` | `2000` | tools per request |
| | `TOOLFORM_MAX_TEXT_CHARS` | `1000000` | characters of text per request |
| | `TOOLFORM_MAX_BODY_BYTES` | `8000000` | bytes of one request body |
| | `TOOLFORM_MAX_JOBS` | `4` | measurements that run at once; as many more may wait |
| | `TOOLFORM_MAX_AB_REQUESTS` | `20000` | requests in one measurement (formats times requests per format) |
| | `TOOLFORM_DEBUG` | off | put the exception text in a 500 response (it always goes to the server log) |
| `--reload` | | off | reload on code changes (development only) |

In Python:

```python
from toolform.serve.app import create_app, run
from toolform.serve.config import ServeConfig

config = ServeConfig(port=9000, endpoint="http://localhost:8000/v1", endpoint_model="Qwen/Qwen3-8B")
app = create_app(config)      # a FastAPI application, for any ASGI server
run(config)                   # or start uvicorn directly
```

## The endpoint for ab-test

`POST /api/v1/ab-test` starts an eight-format measurement against a model. The server
calls the model, not the browser, so it needs to know where the model is:

```bash
toolform serve --endpoint http://localhost:8000/v1 --endpoint-model Qwen/Qwen3-8B
```

With no endpoint configured, the route answers 409 `no_endpoint` with the detail "start
the server with --endpoint URL --endpoint-model ID". Jobs run in a small worker pool (at
most 4 at once by default); poll `GET /api/v1/ab-test/{job_id}` for progress and the
result, and `DELETE /api/v1/ab-test/{job_id}` to cancel one (a queued job never starts,
a running one stops before its next request).

For Qwen 3 and Qwen 3.5, whose chat templates think by default, the route turns
thinking off (`chat_template_kwargs.enable_thinking = false`) unless the request sends
`thinking: true`, as the study did; for other models nothing is sent. A job fails when
every request failed, and its report names no winner when more than a quarter failed,
when every format scored zero, or when every interval overlaps the leader's.

### Why client endpoints are off

With `--allow-client-endpoints`, a request may name its own `base_url`, and the server
will send 400 requests to it. On a server others can reach, that lets anyone make your
server call any address on your network: server-side request forgery. It is off by
default, and the `base_url` field is ignored unless you turn it on. Turn it on only on a
server bound to `127.0.0.1` for your own use.

## Limits

| limit | default | response when exceeded |
|---|---|---|
| tools per request | 2,000 | 413 `payload_too_large` |
| no tools at all | | 422 `loader_error` |
| characters of text per request | 1,000,000 | 413 `payload_too_large` |
| bytes of one request body | 8,000,000 | 413 `payload_too_large`; a `Content-Length` that is not a number is 400 |
| formats in one measurement | 16 (a repeated format runs once) | 422 `validation_error` |
| requests in one measurement | 20,000 | 413 `payload_too_large` |
| measurement jobs | 4 run at once, 4 more may wait | 429 `too_many_jobs` |

The API never loads Python tool modules. Loading a `.py` file executes it, so the
`python` source kind is refused over HTTP; the accepted kinds are `auto`, `openai`,
`anthropic`, `mcp`, `ir` and `typescript`.

## The Host check

The server answers only requests whose `Host` header is `localhost`, `127.0.0.1`,
`::1`, the address it is bound to, or a name you allow with `--allowed-host` (or
`TOOLFORM_ALLOWED_HOSTS`). Any other host gets 421 `misdirected_request`. This closes
DNS rebinding: a web page can point its own domain at 127.0.0.1, and the browser then
treats your local server as that page's own origin, where CORS does not apply. Without
the check, such a page could start measurements on your endpoint key and read the
results. `--allowed-host '*'` turns the check off; do that only on a server no browser
can reach.

## Behind a reverse proxy

The API has no authentication in 0.0.1, and binds to `127.0.0.1` by default. To reach
it from other machines, put it behind a proxy that authenticates, and keep it bound to
the loopback address. Either pass the proxy's host name with `--allowed-host`, or have
the proxy send a local `Host` header, as here. An nginx example:

```nginx
location /toolform/ {
    auth_basic           "ToolForm";
    auth_basic_user_file /etc/nginx/toolform.htpasswd;
    proxy_pass           http://127.0.0.1:8765/;
    proxy_set_header     Host 127.0.0.1;
    proxy_read_timeout   300s;
}
```

If the dashboard is served from another origin, add it with `--cors`.

## Workers

Measurement jobs are held in memory, in the process that started them. With several
uvicorn workers, a job started on one worker cannot be read from another. Run one
worker if you use `ab-test` over HTTP:

```bash
uvicorn --factory toolform.serve.app:create_app --host 127.0.0.1 --port 8765 --workers 1
```

The other routes hold no state, so for them more workers are safe. They are CPU-bound
and fast: rendering, parsing and the advisor read files that ship in the package and
call no model.

## Check it

```bash
curl -s http://127.0.0.1:8765/api/v1/health
# {"status": "ok", "version": "0.0.1", "evidence_version": "2026-09-25.3", "endpoint_configured": false, "allow_client_endpoints": false}
toolform doctor --base-url http://localhost:8000/v1
```

`toolform doctor` checks the install, the evidence files against their checksums, the
registries, the renderers and, with `--base-url`, that the model endpoint answers
`GET /models`.
