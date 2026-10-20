import type { ReactNode } from "react";
import { CodeBlock } from "../ui/CodeBlock";

export interface StageInfo {
  id: string;
  n: string;
  title: string;
  module: string;
  what: ReactNode;
  sdk: string;
  cli: string;
  http: string;
  evidence: ReactNode;
}

export function StageSection({ s }: { s: StageInfo }) {
  return (
    <section className="fw-stage" id={`stage-${s.id}`} aria-labelledby={`stage-${s.id}-h`} tabIndex={-1}>
      <div className="side">
        <div className="label">
          <b>{s.n}</b> / {s.title.toUpperCase()}
        </div>
        <h2 id={`stage-${s.id}-h`}>{s.title}</h2>
        <code>{s.module}</code>
      </div>
      <div>
        <p style={{ fontSize: 17 }}>{s.what}</p>
        <CodeBlock code={s.sdk} lang="python" title="Python" />
        <dl>
          <dt>CLI</dt>
          <dd>
            <code>{s.cli}</code>
          </dd>
          <dt>HTTP</dt>
          <dd>
            <code>{s.http}</code>
          </dd>
          <dt>Evidence</dt>
          <dd className="muted">{s.evidence}</dd>
        </dl>
      </div>
    </section>
  );
}
