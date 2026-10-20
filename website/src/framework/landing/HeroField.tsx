import { useEffect, useRef, useState } from "react";

/* The hero's one animated element: columns of monospace glyphs that resolve,
 * every six seconds, from noise into a fragment of the sample tool
 * (legal_draft_v3) in one of four formats. At most 30 frames a second; paused
 * when off screen or when the tab is hidden; a single still frame under
 * prefers-reduced-motion. The canvas is hidden from screen readers and the
 * fragment on show is in the DOM as text. The fragments are the first lines
 * of the Python renderers' own output for the sample tool (sample_renders.json);
 * the Python signature starts at its docstring, and the natural-language paragraph
 * is wrapped at 56 columns for display. */

export const FRAGMENTS: { format: string; lines: string[] }[] = [
  {
    format: "json_schema_openai",
    lines: [
      "[",
      "  {",
      "    \"type\": \"function\",",
      "    \"function\": {",
      "      \"name\": \"legal_draft_v3\",",
      "      \"description\": \"Draft a new contract. Works on the contracts and clauses data set.\",",
      "      \"parameters\": {",
      "        \"type\": \"object\",",
      "        \"properties\": {",
      "          \"counterparty\": {",
      "            \"type\": \"string\",",
      "            \"description\": \"Other party.\"",
      "          },",
      "          \"value\": {",
      "            \"type\": \"number\",",
      "            \"minimum\": 0,",
      "            \"description\": \"Contract value. Value must be at least 0.\"",
    ],
  },
  {
    format: "xml_schema",
    lines: [
      "<tools>",
      "  <tool>",
      "    <name>legal_draft_v3</name>",
      "    <description>Draft a new contract. Works on the contracts and clauses data set.</description>",
      "    <parameters>",
      "      <parameter name=\"counterparty\" type=\"string\" required=\"true\">",
      "        <description>Other party.</description>",
      "      </parameter>",
      "      <parameter name=\"value\" type=\"number\" required=\"true\">",
      "        <description>Contract value. Value must be at least 0.</description>",
      "      </parameter>",
      "      <parameter name=\"term_months\" type=\"integer\" required=\"true\">",
      "        <description>Length of the term.</description>",
      "      </parameter>",
      "      <parameter name=\"auto_renew\" type=\"boolean\" required=\"false\">",
      "        <description>Whether it renews automatically.</description>",
      "        <default>False</default>",
    ],
  },
  {
    format: "python_stub",
    lines: [
      "    \"\"\"Draft a new contract. Works on the contracts and clauses data set.",
      "",
      "    Args:",
      "        counterparty (str): Other party.",
      "        value (float): Contract value. Value must be at least 0.",
      "        term_months (int): Length of the term.",
      "        auto_renew (bool, optional): Whether it renews automatically.",
      "        contract_details (dict[str, Any], optional): Details of the contract. Keys: contract_id (string, optional), status (enum, optional).",
      "",
      "    Returns:",
      "        the contract id",
      "    \"\"\"",
    ],
  },
  {
    format: "natural_language",
    lines: [
      "1. The tool legal_draft_v3. Draft a new contract. Works",
      "on the contracts and clauses data set. It always needs",
      "counterparty, which is a piece of text (Other party),",
      "value, which is a number at least 0 (Contract value.",
      "Value must be at least 0), and term_months, which is a",
      "whole number between 1 and 600 (Length of the term). You",
      "may also give auto_renew, which is true or false and",
      "defaults to False (Whether it renews automatically), and",
      "contract_details, which is a group of values containing",
      "contract_id (a piece of text), status (one of \"draft\",",
      "\"review\", \"signed\", \"expired\") (Details of the",
      "contract). It gives back the contract id.",
    ],
  },
];

const NOISE = "{}[]<>()=:;,.\"'_/|+-*#01234567890abcdefghijklmnopqrstuvwxyz";
const CYCLE_MS = 6000;
const RESOLVE_MS = 1700;
const DISSOLVE_MS = 700;
const FRAME_MS = 1000 / 30;

function cssVar(el: Element, name: string, fallback: string) {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || fallback;
}

export function HeroField({ onFormat }: { onFormat?: (format: string) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let visible = true;
    let raf = 0;
    let last = 0;
    let start = performance.now();
    let frag = 0;
    let seeds: number[][] = [];
    let w = 0;
    let h = 0;
    const font = 13;
    const cw = 7.9;
    const lh = 20;

    const reseed = () => {
      seeds = FRAGMENTS[frag].lines.map((l) => Array.from({ length: Math.max(l.length, 52) }, () => Math.random()));
    };
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = canvas.getBoundingClientRect();
      w = r.width;
      h = r.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (now: number, still = false) => {
      const t = still ? RESOLVE_MS + 100 : now - start;
      if (!still && t > CYCLE_MS) {
        frag = (frag + 1) % FRAGMENTS.length;
        start = now;
        reseed();
        setIdx(frag);
        onFormat?.(FRAGMENTS[frag].format);
      }
      const text = cssVar(canvas, "--fw-text-muted", "#9AA6B5");
      const faint = cssVar(canvas, "--fw-text-faint", "#7D8898");
      const accent = cssVar(canvas, "--fw-accent", "#4FE3C1");
      ctx.clearRect(0, 0, w, h);
      ctx.font = `${font}px "JetBrains Mono", ui-monospace, monospace`;
      ctx.textBaseline = "top";
      const lines = FRAGMENTS[frag].lines;
      const cols = Math.max(...lines.map((l) => l.length), 44);
      // Long lines run off the right edge; the block is placed as if 60 wide.
      const blockW = Math.min(cols, 60) * cw;
      const x0 = Math.max(w * 0.52, w - blockW - 48);
      const y0 = Math.max(24, (h - lines.length * lh) / 2);
      if (w < 900) return; // on narrow screens the text sits over the field; keep the grid only
      const dissolve = !still && t > CYCLE_MS - DISSOLVE_MS ? (t - (CYCLE_MS - DISSOLVE_MS)) / DISSOLVE_MS : 0;
      ctx.fillStyle = faint;
      ctx.globalAlpha = 0.55;
      ctx.fillText(`// ${FRAGMENTS[frag].format}`, x0, y0 - lh * 1.4);
      for (let li = 0; li < lines.length; li++) {
        const line = lines[li];
        const row = seeds[li] ?? [];
        for (let ci = 0; ci < cols; ci++) {
          const target = line[ci] ?? " ";
          const s = row[ci] ?? 0.5;
          const resolveAt = s * RESOLVE_MS * 0.85 + (ci / cols) * RESOLVE_MS * 0.15;
          const resolved = t >= resolveAt && s > dissolve;
          const x = x0 + ci * cw;
          const y = y0 + li * lh;
          if (resolved) {
            if (target === " ") continue;
            const fresh = t - resolveAt < 140 && !still;
            ctx.fillStyle = fresh ? accent : text;
            ctx.globalAlpha = fresh ? 1 : 0.9;
            ctx.fillText(target, x, y);
          } else if (target !== " " || s < 0.18) {
            ctx.fillStyle = faint;
            ctx.globalAlpha = 0.18 + 0.2 * Math.abs(Math.sin(now / 90 + s * 40));
            ctx.fillText(NOISE[Math.floor((s * 997 + now / 60) % NOISE.length)], x, y);
          }
        }
      }
      ctx.globalAlpha = 1;
    };

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (!visible || document.hidden) return;
      if (now - last < FRAME_MS) return;
      last = now;
      draw(now);
    };

    reseed();
    resize();
    const onResize = () => {
      resize();
      if (reduce.matches) draw(performance.now(), true);
    };
    window.addEventListener("resize", onResize);
    const io = new IntersectionObserver((entries) => {
      visible = entries.some((e) => e.isIntersecting);
    });
    io.observe(canvas);
    const themeObs = new MutationObserver(() => reduce.matches && draw(performance.now(), true));
    themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    if (reduce.matches) draw(performance.now(), true);
    else raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      io.disconnect();
      themeObs.disconnect();
    };
  }, [onFormat]);

  return (
    <>
      <canvas ref={ref} aria-hidden="true" />
      <div className="sr-only" aria-live="off">
        The sample tool legal_draft_v3 written as {FRAGMENTS[idx].format}: {FRAGMENTS[idx].lines.join(" ")}
      </div>
    </>
  );
}
