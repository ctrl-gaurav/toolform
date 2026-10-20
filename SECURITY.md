# Security Policy

## Reporting a vulnerability

Please report security issues privately through GitHub Security Advisories ("Report a
vulnerability" on the repository's Security tab) rather than in a public issue. We aim to
acknowledge reports within 72 hours.

## Notes

- **Python tool files run code.** Loading tools from a `.py` file (`Toolset.from_python`,
  `--from python`) imports the module, which executes it. Load Python tool files only from sources
  you trust; JSON, MCP and TypeScript inputs are parsed, never executed.
- **Tool descriptions are an attack surface.** The study found that models follow an instruction
  hidden in a third-party tool's description on 38 to 54% of turns. `toolform guard` flags and
  strips such text, but it is a heuristic detector, not a guarantee.
- **The HTTP API has no authentication.** `toolform serve` binds to `127.0.0.1` by default; put it
  behind your own gateway before exposing it, and enable client-supplied endpoints only when you
  trust the clients.
- **Keys** for model endpoints are read from the environment by name and are never logged.
