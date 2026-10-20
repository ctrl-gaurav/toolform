---
title: Contributing
---

# Contributing

Bug reports, documentation fixes, new loaders and new formats or protocols are all welcome.

## Layout

```text
toolform/
  ir/          the canonical tool representation every format renders from
  formats/     the 129 schema renderers, plus the two-stage variants
  protocols/   the 31 answer-protocol parsers
  eval/        the three grading rules and the metrics
  generator/   generated tools with executable semantics (used by measure and the samples)
  prompts/     prompt assembly, as the study built it
  sdk/         Toolset, loaders, render, parse, validation, clients, the call loop
  advisor/     the recommendation, the evidence files (advisor/data/) and measure
  guard/       the description-channel scanner and cleaner
  catalogue/   retrieval, names-first disclosure, token budgets, plans
  serve/       the HTTP API (the serve extra)
  app/         the command line
website/       the landing page, the framework page and the dashboard
docs/          this documentation
examples/      runnable examples and the example tool files
tests/         the test suite
```

## Development setup

```bash
git clone https://github.com/ctrl-gaurav/toolform && cd toolform
python -m venv .venv && source .venv/bin/activate
pip install -e ".[serve,dev]"
```

## Checks

```bash
ruff check toolform tests examples
ruff format --check toolform tests examples
pytest                                   # no GPU, network or API key needed
python -m build && twine check dist/*    # the package builds and its README renders
```

The website and the documentation build with Node 20:

```bash
(cd website && npm ci && npm run build && npx vitest run)
(cd docs && npm ci && npm run build)
```

## Guidelines

* Keep the core install light: heavy dependencies belong in extras.
* Add tests for new behaviour; they must run offline.
* Every number the advisor shows comes from the evidence files. Do not edit
  `toolform/advisor/data/` by hand: the files are built from the study's tables and their
  hashes are checked by `toolform doctor`.
* Renderers and parsers are the ones the study measured. A change to one changes what a
  study number refers to; open an issue first.
* Update the documentation when the public API changes.

## Adding a format or a protocol

A new format goes in `toolform/formats/` and registers itself; a new protocol goes in
`toolform/protocols/`. Both render and parse at once. A new entry has no study numbers
until someone measures it: the advisor ranks it only if you pass it in `candidates`, with
no evidence and a warning. `toolform ab-test` and `toolform.advisor.ab_test` measure it on
your own model.

## Releases

The version is `toolform.sdk.constants.FRAMEWORK_VERSION`. Every release has an entry in
[the changelog](changelog.md).

## Code of Conduct

This project follows the
[Contributor Covenant](https://github.com/ctrl-gaurav/toolform/blob/main/CODE_OF_CONDUCT.md).
