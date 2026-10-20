import type { Rule, Zoo, FamilyRow, Tiers } from "../lib/evidence";
import { RULE_TEXT, type Situation } from "../lib/advisor";
import { CROSSING_PROTOCOLS } from "../lib/render/protocols";
import { Field, FieldGroup } from "../ui/Field";
import { Segmented } from "../ui/Segmented";
import { ToolsInput, type ToolsValue } from "./ToolsInput";

const EXP = [0, 1, 2, 3, 4, 5, 6, 7, 8];

export function AdvisorForm({
  s,
  set,
  zoo,
  families,
  tiers,
  tools,
  setTools,
  useTools,
  setUseTools,
}: {
  s: Situation;
  set: (patch: Partial<Situation>) => void;
  zoo: Zoo | null;
  families: FamilyRow[];
  tiers: Tiers | null;
  tools: ToolsValue;
  setTools: (v: ToolsValue) => void;
  useTools: boolean;
  setUseTools: (b: boolean) => void;
}) {
  const fromTools = useTools && !!tools.loaded;
  const numOrNull = (v: string) => (v.trim() === "" ? null : Number(v));
  const exp = Math.log2(Math.max(1, s.n_tools));
  const tierTitles = Object.fromEntries(Object.entries(tiers?.definitions ?? {}).map(([k, v]) => [k, `Tier ${k}: ${v}`]));
  return (
    <form onSubmit={(e) => e.preventDefault()} aria-label="The situation">
      <Field label="Model" hint="A model id or name: a zoo id, an anchor such as claude-opus-5-5, or any id the family patterns recognise.">
        <input type="text" list="fw-zoo-ids" value={s.model ?? ""} placeholder="Qwen/Qwen3-8B" spellCheck={false} onChange={(e) => set({ model: e.target.value || null })} />
      </Field>
      <datalist id="fw-zoo-ids">
        {(zoo?.models ?? []).map((m) => (
          <option key={m.id} value={m.id} />
        ))}
      </datalist>
      <div className="fw-grid2" style={{ gap: 12 }}>
        <Field label="Family (optional)">
          <select value={s.family ?? ""} onChange={(e) => set({ family: e.target.value || null })}>
            <option value="">from the model</option>
            {families
              .filter((f) => f.kind === "open")
              .map((f) => (
                <option key={f.family!} value={f.family!}>
                  {f.label}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Parameters (B)">
          <input type="number" min={0} step="any" value={s.params_b ?? ""} placeholder="from the id" onChange={(e) => set({ params_b: numOrNull(e.target.value) })} />
        </Field>
      </div>

      <div className="fw-field">
        <label className="check">
          <input type="checkbox" checked={useTools} onChange={(e) => setUseTools(e.target.checked)} />
          Paste my tools (the tool count and tier then come from them)
        </label>
      </div>
      {useTools && <ToolsInput value={tools} onChange={setTools} id="fw-advisor-tools" rows={8} />}

      <FieldGroup label={`Tools shown: ${s.n_tools}`} hint={fromTools ? "From your tools." : "A log scale from 1 to 256; the box takes any whole number."}>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input
            type="range"
            min={0}
            max={8}
            step={0.01}
            value={exp}
            disabled={fromTools}
            aria-label="Tools shown, log scale"
            aria-valuetext={`${s.n_tools} tools`}
            onChange={(e) => {
              const v = Number(e.target.value);
              const snapped = EXP.find((x) => Math.abs(x - v) < 0.08);
              set({ n_tools: Math.max(1, Math.round(2 ** (snapped ?? v))) });
            }}
          />
          <input
            type="number"
            min={1}
            style={{ width: 90 }}
            aria-label="Tools shown"
            value={s.n_tools}
            disabled={fromTools}
            onChange={(e) => set({ n_tools: Math.max(1, Math.round(Number(e.target.value) || 1)) })}
          />
        </div>
      </FieldGroup>

      <FieldGroup label="Complexity tier" hint={tiers?.definitions?.[String(s.tier)] ? `Tier ${s.tier}: ${tiers.definitions[String(s.tier)]}.` : undefined}>
        <Segmented
          label="Complexity tier"
          value={s.tier}
          onChange={(v) => set({ tier: v })}
          titles={tierTitles}
          options={[1, 2, 3, 4, 5].map((t) => ({ value: t, label: String(t) }))}
        />
      </FieldGroup>

      <Field label="Token budget for the tool block (optional)">
        <input type="number" min={1} value={s.token_budget ?? ""} placeholder="no limit" onChange={(e) => set({ token_budget: numOrNull(e.target.value) })} />
      </Field>
      <Field label="Context window (optional)" hint="Defaults to the model's window when the zoo knows it.">
        <input type="number" min={1} value={s.context_tokens ?? ""} placeholder="from the model" onChange={(e) => set({ context_tokens: numOrNull(e.target.value) })} />
      </Field>

      <FieldGroup label="Objective">
        <Segmented
          label="Objective"
          value={s.objective}
          onChange={(v) => set({ objective: v })}
          options={[
            { value: "accuracy", label: "accuracy" },
            { value: "cost", label: "accuracy per cost" },
          ]}
        />
      </FieldGroup>
      {s.objective === "cost" && (
        <Field label="Price vector" hint="The paper's two relative price vectors (tab_cost), not real prices.">
          <select value={s.price} onChange={(e) => set({ price: e.target.value as Situation["price"] })}>
            <option value="frontier_api">frontier API: 1 / 0.1 cached / 5 per million, schema cached</option>
            <option value="self_hosted">self-hosted: 0.2 / 0.2 / 2 per million</option>
          </select>
        </Field>
      )}

      <FieldGroup label="Grading rule" hint={RULE_TEXT[s.rule]}>
        <Segmented
          label="Grading rule"
          value={s.rule}
          onChange={(v) => set({ rule: v as Rule })}
          options={[
            { value: "main", label: "main" },
            { value: "symmetric", label: "symmetric" },
            { value: "as_written", label: "as written" },
          ]}
        />
      </FieldGroup>

      <Field label="Answer protocol (optional)" hint="Leave open and the advisor switches protocol only on a measured gain of 2.0 or more.">
        <select value={s.protocol ?? ""} onChange={(e) => set({ protocol: e.target.value || null })}>
          <option value="">the format's default</option>
          {CROSSING_PROTOCOLS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </Field>

      <div className="fw-field">
        <label className="check">
          <input type="checkbox" checked={s.third_party_tools} onChange={(e) => set({ third_party_tools: e.target.checked })} />
          The tools come from third parties (MCP servers, plugins)
        </label>
      </div>
    </form>
  );
}
