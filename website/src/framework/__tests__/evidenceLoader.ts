/* Build the advisor's Evidence object from the files on disk, for tests. */
import type { Evidence } from "../lib/evidence";
import { ADVISOR_FILES } from "../lib/evidence";
import { readEvidence } from "./fixtures";

export function diskEvidence(): Evidence | null {
  const out: Record<string, unknown> = {};
  for (const n of ADVISOR_FILES) {
    const env = readEvidence<{ data: unknown }>(n);
    if (!env) return null;
    out[n] = env.data;
  }
  const surface = readEvidence<{ data: unknown }>("surface");
  const manifest = readEvidence<{ evidence_version: string }>("manifest");
  return { ...(out as Omit<Evidence, "surface" | "version">), surface: (surface?.data as Evidence["surface"]) ?? null, version: manifest?.evidence_version ?? "unknown" };
}
