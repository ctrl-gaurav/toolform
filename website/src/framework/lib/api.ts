/* The optional HTTP API (toolform serve), section (f) of the design.
 *
 * The base URL comes from the `api` query parameter, then
 * localStorage["ts-api"], then http://127.0.0.1:8765. The dashboard probes
 * GET /api/v1/health only when the reader asked for the API: an `api` query
 * parameter, a base saved by an earlier Connect, or a press of Connect. A
 * public page that reaches 127.0.0.1 on its own can raise a local-network
 * permission prompt for readers who never run toolform serve, so it does
 * not. Offline, everything except parsing and the 121 non-core renderers
 * runs in the browser from the evidence files; online, the advisor, the
 * playground and the guard's catalogue scan call the API and get the same
 * shapes back. A single pasted description is always scanned in the browser.
 */

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Recommendation, Situation } from "./advisor";
import type { GuardReport } from "./guard";

export const DEFAULT_API = "http://127.0.0.1:8765";

export interface Health {
  status: string;
  version: string;
  evidence_version: string;
  endpoint_configured: boolean;
  allow_client_endpoints: boolean;
}

export interface ToolsBody {
  source: "auto" | "openai" | "anthropic" | "mcp" | "ir" | "typescript";
  payload: unknown;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
  ) {
    super(message);
  }
}

function queryParam(name: string): string | null {
  try {
    const fromSearch = new URLSearchParams(window.location.search).get(name);
    if (fromSearch) return fromSearch;
    const hash = window.location.hash;
    const q = hash.indexOf("?");
    return q >= 0 ? new URLSearchParams(hash.slice(q + 1)).get(name) : null;
  } catch {
    return null;
  }
}

/** Whether the reader asked for the API before this page load: an `api` parameter or a saved base. */
export function apiRequested(): boolean {
  if (queryParam("api")) return true;
  try {
    return !!localStorage.getItem("ts-api");
  } catch {
    return false;
  }
}

export function initialApiBase(): string {
  const q = queryParam("api");
  if (q) return q.replace(/\/+$/, "");
  try {
    const saved = localStorage.getItem("ts-api");
    if (saved) return saved.replace(/\/+$/, "");
  } catch {
    /* storage blocked: fall through */
  }
  return DEFAULT_API;
}

export async function probe(base: string, timeoutMs = 1500): Promise<Health | null> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`${base}/api/v1/health`, { signal: ctrl.signal });
    if (!r.ok) return null;
    const h = (await r.json()) as Health;
    return h && h.status === "ok" ? h : null;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timer);
  }
}

async function post<T>(base: string, path: string, body: unknown): Promise<T> {
  const r = await fetch(`${base}/api/v1${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data as { error?: string; detail?: unknown };
    throw new ApiError(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail ?? data), r.status, d.error ?? "error");
  }
  return data as T;
}

export interface RenderResponse {
  format_id: string;
  protocol_id: string;
  tool_block: string;
  instructions: string;
  system_prompt: string;
  messages: { role: string; content: string }[] | null;
  chars: number;
  tokens_estimate: number;
}

export interface ParsedCallOut {
  name: string;
  arguments: Record<string, unknown>;
  resolved_name: string | null;
  normalized_arguments: Record<string, unknown> | null;
  valid: boolean;
  validation: unknown;
  repairs: string[];
  accepted: boolean;
  reason: string;
}
export interface ParseResponse {
  protocol_id: string;
  rule: string;
  calls: ParsedCallOut[];
  rejected: ParsedCallOut[];
  parsed_strict: boolean;
  parsed_lenient: boolean;
  format_compliant: boolean;
  no_call_declared: boolean;
  hallucinated: string[];
  note: string;
  ok: boolean;
}

export const api = {
  recommend: (base: string, situation: Situation, tools: ToolsBody | null) => post<Recommendation>(base, "/recommend", { situation, tools }),
  render: (base: string, body: { tools: ToolsBody; format: string; protocol: string | null; options: Record<string, unknown>; request: string | null }) =>
    post<RenderResponse>(base, "/render", body),
  parse: (base: string, body: { tools: ToolsBody; text: string; protocol: string; rule: string; validate: boolean; lenient_fallback: boolean }) =>
    post<ParseResponse>(base, "/parse", body),
  guard: (base: string, body: { tools: ToolsBody; strictness: string; action: string; scope: string }) =>
    post<GuardReport>(base, "/guard", body),
};

/* ------------------------------------------------------------------ context */

export interface ApiState {
  base: string;
  /** "idle": the API was never asked for, so nothing was probed. */
  status: "idle" | "checking" | "online" | "offline";
  health: Health | null;
  retry: () => void;
  setBase: (b: string) => void;
}

const Ctx = createContext<ApiState | null>(null);

export function ApiProvider({ children }: { children: ReactNode }) {
  const [base, setBaseState] = useState(initialApiBase);
  const [health, setHealth] = useState<Health | null>(null);
  const [wanted, setWanted] = useState(apiRequested);
  const [status, setStatus] = useState<ApiState["status"]>(() => (apiRequested() ? "checking" : "idle"));
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!wanted) return;
    let alive = true;
    setStatus("checking");
    probe(base).then((h) => {
      if (!alive) return;
      setHealth(h);
      setStatus(h ? "online" : "offline");
    });
    return () => {
      alive = false;
    };
  }, [base, nonce, wanted]);

  const retry = useCallback(() => {
    setWanted(true);
    setNonce((n) => n + 1);
  }, []);
  const setBase = useCallback((b: string) => {
    setWanted(true);
    const clean = b.trim().replace(/\/+$/, "") || DEFAULT_API;
    try {
      localStorage.setItem("ts-api", clean);
    } catch {
      /* storage blocked: the choice lasts for this page */
    }
    setBaseState(clean);
  }, []);

  const value = useMemo(() => ({ base, status, health, retry, setBase }), [base, status, health, retry, setBase]);
  return createElement(Ctx.Provider, { value }, children);
}

export function useApi(): ApiState {
  const v = useContext(Ctx);
  if (!v) return { base: DEFAULT_API, status: "idle", health: null, retry: () => {}, setBase: () => {} };
  return v;
}
