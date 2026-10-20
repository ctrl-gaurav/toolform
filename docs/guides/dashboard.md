---
title: Use the dashboard
order: 47
section: Guides
summary: The advisor, the playground, the guard demo and the evidence explorer in the browser, offline or connected to toolform serve.
---

# Use the dashboard

The dashboard is part of the ToolForm site, at
[ctrl-gaurav.github.io/toolform/#/dashboard](https://ctrl-gaurav.github.io/toolform/#/dashboard/advisor).
It has four panels. All four work offline in your browser from the study's evidence,
which the site carries as static JSON. Connected to a local `toolform serve`, the
playground can also render any of the 129 formats for your own tools and parse replies.

## The four panels

### Advisor

The advisor of [Choose a format for your model](choose-a-format.md), in a form. Inputs:
the model (with suggestions from the model zoo), the family, the parameters in
billions, the tool count (1 to 256 on a log scale), the tier (1 to 5, each with its
definition), a token budget, the objective (accuracy or cost) and its price vector, the
grading rule, a fixed protocol, and whether the tools come from a third party. "Paste
my tools" opens the tools input; the tool count and the tier then come from your tools.

The result shows the format and the protocol, the expected accuracy with the range
across the table values it rests on drawn as a bar, the token cost, the catalogue strategy, the
warnings, the explanation, the alternatives, and a chart of the eight core formats'
expected accuracies. Every evidence row names its source table and links to the chart
behind it in the evidence explorer. "Copy Python" and "Copy CLI" give you the exact
`recommend(...)` call and `toolform recommend ...` command for these inputs.

A badge says where the result came from: "computed in your browser from evidence
`<version>`" or "from toolform serve at `<address>`". The browser's advisor is a port of
the Python advisor and is tested against it on about 300 cases, so the two agree.

### Playground

Paste tools as OpenAI, Anthropic, MCP or IR JSON (or press "Sample tool" or "Three real
tools"), choose a format and a protocol, set the rendering options, and type a request.
The panel shows the tool block, the protocol instruction and the system prompt, with
character and token estimates.

Below that, "All eight side by side" renders your tools in the eight core formats with
their tokens and their accuracy on the study's main grid (tab:main). "Every format for
the sample tool" shows the 129 study formats for the study's sample tool, filterable by
family, with invented formats marked "(novel)".

### Guard demo

Paste one description or a whole catalogue, choose the strictness, and see each
finding's span highlighted by severity, the finding list (rule id, name, severity,
message), the text after strip (whole sentences with a high finding removed), and the
injection evidence. The examples include the study's hijack sentence, a decoy that
names another tool, a benign real tool, and zero-width characters. The guard is a
rule-based detector: the study measured how often models follow hidden instructions,
not this detector. On a held-out set of 50 descriptions it flagged 12 of 25 injected
ones and 1 of 25 benign ones at high severity. See [Guard third-party
tools](guard-third-party-tools.md).

### Evidence explorer

The study's charts, each with a title that states the finding, a caption naming the
source table and its conditions, a "show as table" toggle and a link to the JSON file:
the schema ladder; the same answers under three grading rules; format by protocol under
each rule; accuracy by tool count; hidden instructions by format; how the selection
strategies compare; tokens against accuracy; families by format; and two-stage
disclosure by tool count. Each chart has its own address,
`#/dashboard/evidence?chart=<id>`, so a link can point at one chart.

## Offline and online

| task | offline (browser only) | online (with `toolform serve`) |
|---|---|---|
| advisor | yes | yes, through `POST /api/v1/recommend` |
| render your tools in the eight core formats | yes | yes |
| render your tools in the other 121 formats | no | yes, through `POST /api/v1/render` |
| every format for the sample tool | yes | yes |
| parse a reply | no ("Parsing runs in the API: toolform serve") | yes, through `POST /api/v1/parse` |
| guard | yes | a pasted catalogue through `POST /api/v1/guard`; a single pasted description is always scanned in the browser |
| evidence explorer | yes | yes |

Offline, the eight core renderers and the guard run as TypeScript ports of the Python
code, checked against it on shared test cases. The other 121 renderers and the parsers
exist only in Python.

## Connect to toolform serve

Start the API on your machine (it needs the `serve` extra):

```bash
git clone https://github.com/ctrl-gaurav/toolform && pip install -e "./toolform[serve]"
toolform serve
# ToolForm API on http://127.0.0.1:8765 (docs at /docs, OpenAPI at /openapi.json)
```

Open the dashboard and press "Connect to local API". The page does not contact a
local server on its own: a public page that reaches 127.0.0.1 unasked can make the
browser show a local-network permission prompt to readers who never run
`toolform serve`. It probes `GET /api/v1/health` (1.5 second timeout) only when the
address comes from an `api` query parameter, when you saved one with an earlier
Connect, or when you press Connect or Retry. The address is taken from, in order:

1. the `api` query parameter:
   `https://ctrl-gaurav.github.io/toolform/#/dashboard/advisor?api=http://127.0.0.1:9000`;
2. the address you saved earlier (kept in your browser's local storage as `ts-api`);
3. `http://127.0.0.1:8765`.

### CORS and private network access

The public site runs on `https://ctrl-gaurav.github.io`, and the API on your own
machine. For the browser to allow that call, the server must name the site as an
allowed origin, and answer the private network access preflight that Chrome sends
before a public page calls a local address. `toolform serve` does both by default: its
allowed origins are `https://ctrl-gaurav.github.io` and the local development addresses
(`http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:4173`,
`http://127.0.0.1:4173`), and it answers `Access-Control-Allow-Private-Network: true` on
preflight. If you host the site elsewhere, add its origin with `--cors ORIGIN`.

Some browsers block a page served over HTTPS from calling a plain-HTTP address, even on
your own machine. If the status stays offline while the server is running, run the
site locally:

```bash
cd website
npm ci
npm run dev        # http://localhost:5173/#/dashboard/advisor
```

## Run the site yourself

The site is static. `cd website && npm ci && npm run build` writes `dist/`, which any
static host can serve; it uses relative paths and a hash router, so it works from any
folder. The evidence is copied into `website/public/` by `npm run sync` from
`toolform/advisor/data/`.
