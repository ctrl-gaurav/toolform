import { factMap, useEvidence } from "../lib/evidence";

/* The study in seven numbers, read from facts.json at run time. */
export function FactStrip() {
  const { data } = useEvidence("facts");
  const f = factMap(data);
  const v = (id: string, fallback: string) => (f[id] ? f[id].value.toLocaleString("en-US") : fallback);
  const items: [string, string][] = [
    [v("n_formats", "129"), "schema formats"],
    [v("n_protocols", "31"), "answer protocols"],
    [v("n_rules", "3"), "grading rules"],
    [`${v("n_open_models", "100")} + ${v("n_proprietary_models", "11")}`, "open-source and proprietary models"],
    [v("n_domains", "24"), "generated domains with executable tools"],
    [v("n_real_tools", "66"), `real tools, ${v("n_real_requests", "1,248")} human-written requests`],
    [v("n_public_benchmarks", "6"), "public benchmarks"],
  ];
  return (
    <section className="fw-facts-band" aria-label="The study in numbers">
      <div className="wrap">
        <div className="fw-facts">
          {items.map(([val, k]) => (
            <div key={k}>
              <div className="v">{val}</div>
              <div className="k">{k}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
