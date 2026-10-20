/* Test helpers: read an evidence file from public/data/framework/, or report
 * that it is missing so the parity test can skip with a message. */

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

// TS_EVIDENCE_DIR points the tests at another copy, for example the package's own data.
export const FRAMEWORK_DATA = process.env.TS_EVIDENCE_DIR ? resolve(process.env.TS_EVIDENCE_DIR) : resolve(__dirname, "../../../public/data/framework");

export function readEvidence<T = unknown>(name: string): T | null {
  const p = resolve(FRAMEWORK_DATA, `${name}.json`);
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, "utf-8")) as T;
}

export function trimLines(s: string): string {
  return s
    .split("\n")
    .map((l) => l.replace(/\s+$/, ""))
    .join("\n");
}
