import type { Finding, Severity } from "../lib/guard";
import { SEVERITY_ORDER } from "../lib/guard";

/* The text with each finding's span marked by severity. Overlapping spans
 * take the most severe finding; the severity word is in the title and in the
 * list beside it, so colour is never the only signal. */
export function HighlightedText({ text, findings }: { text: string; findings: Finding[] }) {
  const sev: (Severity | null)[] = new Array(text.length).fill(null);
  const rules: string[][] = Array.from({ length: text.length }, () => []);
  for (const f of findings) {
    for (let i = f.start; i < f.end && i < text.length; i++) {
      if (sev[i] === null || SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[sev[i]!]) sev[i] = f.severity;
      if (!rules[i].includes(f.rule_id)) rules[i].push(f.rule_id);
    }
  }
  const parts: { s: Severity | null; text: string; rules: string }[] = [];
  for (let i = 0; i < text.length; i++) {
    const r = rules[i].join(", ");
    const last = parts[parts.length - 1];
    if (last && last.s === sev[i] && last.rules === r) last.text += text[i];
    else parts.push({ s: sev[i], text: text[i], rules: r });
  }
  return (
    <pre className="fw-hl" tabIndex={0} aria-label="The text with findings marked">
      {parts.map((p, i) =>
        p.s ? (
          <mark key={i} className={p.s} title={`${p.s}: ${p.rules}`}>
            {p.text.replace(/[\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g, (c) => `[U+${c.charCodeAt(0).toString(16).toUpperCase().padStart(4, "0")}]`)}
            <span className="sr-only"> ({p.s} finding: {p.rules})</span>
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </pre>
  );
}
