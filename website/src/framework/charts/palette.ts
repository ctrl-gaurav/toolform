/* Chart colours. One colour per core format, the same in every chart, as CSS
 * variables so the light and dark steps swap with the theme (tokens.css has
 * the validated values and the reason they differ from the design's list). */

import { useEffect, useState } from "react";

export const FORMAT_VAR: Record<string, string> = {
  xml_schema: "--fw-s-xml",
  natural_language: "--fw-s-nl",
  python_stub: "--fw-s-py",
  json_schema_openai: "--fw-s-json",
  yaml_schema: "--fw-s-yaml",
  typescript: "--fw-s-ts",
  markdown_table: "--fw-s-md",
  json_minimal: "--fw-s-min",
};

/** The first three slots validate against each other in every pair, so a
 * three-series chart (the grading rules, the disclosure arms) uses them. */
export const SERIES_VARS = ["--fw-s-xml", "--fw-s-nl", "--fw-s-py"];

export function fmtColor(f: string): string {
  return `var(${FORMAT_VAR[f] ?? "--fw-text-faint"})`;
}

function readVars(names: string[]): Record<string, string> {
  const el = document.querySelector(".fw") ?? document.documentElement;
  const cs = getComputedStyle(el);
  return Object.fromEntries(names.map((n) => [n, cs.getPropertyValue(n).trim()]));
}

/** Resolved colours, re-read when the theme changes (SVG fill attributes in
 * Recharts take CSS variables fine, but gradients and computed text need hex). */
export function useThemeColors(): Record<string, string> {
  const names = [...Object.values(FORMAT_VAR), "--fw-text", "--fw-text-muted", "--fw-text-faint", "--fw-border", "--fw-accent", "--fw-surface", "--fw-surface-2", "--fw-seq-lo", "--fw-seq-hi", "--fw-bg"];
  const [c, setC] = useState<Record<string, string>>(() => readVars(names));
  useEffect(() => {
    const update = () => setC(readVars(names));
    update();
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return c;
}

function hexToRgb(h: string): [number, number, number] {
  const m = h.replace("#", "");
  const n = m.length === 3 ? m.split("").map((x) => x + x).join("") : m;
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)];
}

/** A one-hue sequential scale from the surface to the accent blue. */
export function seqColor(t: number, lo: string, hi: string): string {
  const a = hexToRgb(lo || "#10151e");
  const b = hexToRgb(hi || "#3987e5");
  const k = Math.max(0, Math.min(1, t));
  const mix = a.map((x, i) => Math.round(x + (b[i] - x) * k));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}

/** Text colour for a filled cell, by the cell's luminance. */
export function inkOn(rgb: string, light: string, dark: string): string {
  const m = rgb.match(/\d+/g);
  if (!m) return light;
  const [r, g, b] = m.map(Number).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return L > 0.3 ? dark : light;
}
