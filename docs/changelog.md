---
title: Changelog
---

# Changelog

## 0.0.1

The first public release.

- **Advisor:** recommends a schema format and an answer protocol for a model and a tool set
  from the study's per-factor tables, names the table behind every number, and falls back
  from model to family to pooled evidence with a warning. `measure` tests eight formats on
  your own endpoint in 400 requests.
- **Rendering and parsing:** 129 schema formats, the two-stage variants and 31 answer
  protocols, each the one the study measured, with the three grading rules as explicit
  options and argument validation against the schema.
- **Guard:** scans tool descriptions for hidden instructions and other risky text, and
  cleans them.
- **Catalogue:** names-first disclosure, BM25 and embedding retrieval, token budgets and a
  planner that picks between them.
- **Interfaces:** a Python SDK, the `toolform` command line, an HTTP API (the `serve`
  extra) and a web dashboard that runs offline from the evidence.
- **Loaders:** OpenAI, Anthropic and MCP tool definitions, Python functions and TypeScript
  declarations; converters between them.
