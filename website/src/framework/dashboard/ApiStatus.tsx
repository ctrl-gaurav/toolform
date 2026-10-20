import { useEffect, useState } from "react";
import { useApi } from "../lib/api";
import { useManifest } from "../lib/evidence";
import { Badge } from "../ui/Badge";

/* Where the dashboard's answers come from: the browser, from the evidence
 * files, or a toolform serve process the reader started. */
export function ApiStatus() {
  const { base, status, health, retry, setBase } = useApi();
  const manifest = useManifest();
  const [draft, setDraft] = useState(base);
  useEffect(() => setDraft(base), [base]);
  return (
    <div className="fw-api" aria-live="polite">
      {status === "checking" && <Badge dot>checking {base}</Badge>}
      {status === "online" && (
        <Badge tone="ok" dot title={`API ${health?.version}, evidence ${health?.evidence_version}`}>
          API online: toolform serve at {base}
        </Badge>
      )}
      {status === "offline" && (
        <Badge tone="accent" dot title="Start toolform serve and press Connect to use the API">
          offline: no API at {base}; computed in your browser from evidence {manifest?.evidence_version ?? ""}
        </Badge>
      )}
      {status === "idle" && (
        <Badge tone="accent" dot title="The page does not contact a local server until you press Connect">
          computed in your browser from evidence {manifest?.evidence_version ?? ""}
        </Badge>
      )}
      <form
        className="row"
        style={{ gap: 6 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim() === base) retry();
          else setBase(draft);
        }}
      >
        <label htmlFor="fw-api-base" className="sr-only">
          API base URL
        </label>
        <input id="fw-api-base" type="url" value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false} />
        <button type="submit" className="fw-btn small">
          {status === "idle" ? "Connect to local API" : "Retry"}
        </button>
      </form>
    </div>
  );
}
