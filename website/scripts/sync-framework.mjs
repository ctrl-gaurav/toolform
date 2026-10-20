#!/usr/bin/env node
/* Copy what the site needs from outside website/, so the site builds from its
 * own folder and never reads outside it at run time.
 *
 *   ../toolform/advisor/data/*.json -> public/data/framework/   (a mirror: same bytes)
 *   ../docs/framework/**\/*.md        -> public/docs/            (only if that folder exists)
 *
 * The manifest lists every doc as {slug, title, section, order, summary, path},
 * from each file's front matter.
 *
 *   node scripts/sync-framework.mjs              copy
 *   node scripts/sync-framework.mjs --check      compare, exit 1 on any difference
 *   --if-present                                 skip a source folder that does not exist
 *                                                (the committed copies then stay)
 */

import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const site = resolve(here, "..");
const repo = resolve(site, "..");
const args = new Set(process.argv.slice(2));
const CHECK = args.has("--check");
const IF_PRESENT = args.has("--if-present");

const DATA_SRC = join(repo, "toolform", "advisor", "data");
const DATA_DST = join(site, "public", "data", "framework");
const DOCS_SRC = join(repo, "docs", "framework");
const DOCS_DST = join(site, "public", "docs");

let problems = 0;
const note = (m) => console.log(`sync: ${m}`);
const fail = (m) => {
  problems++;
  console.error(`sync: ${m}`);
};

function walk(dir, ext) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) out.push(...walk(p, ext));
    else if (name.endsWith(ext)) out.push(p);
  }
  return out.sort();
}

function writeIfChanged(dst, content) {
  const same = existsSync(dst) && Buffer.compare(readFileSync(dst), Buffer.from(content)) === 0;
  if (CHECK) {
    if (!same) fail(`${relative(site, dst)} differs from its source`);
    return;
  }
  if (!same) {
    mkdirSync(dirname(dst), { recursive: true });
    writeFileSync(dst, content);
  }
}

function prune(dstDir, keep, ext) {
  if (!existsSync(dstDir)) return;
  for (const p of walk(dstDir, ext)) {
    if (keep.has(p)) continue;
    if (CHECK) fail(`${relative(site, p)} has no source`);
    else rmSync(p);
  }
}

function frontMatter(text) {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  const meta = {};
  if (!m) return meta;
  for (const line of m[1].split(/\r?\n/)) {
    const kv = line.match(/^([A-Za-z_]+):\s*(.*?)\s*(#.*)?$/);
    if (kv) meta[kv[1]] = kv[2].replace(/^["']|["']$/g, "");
  }
  return meta;
}

function firstHeading(text) {
  const m = text.replace(/^---[\s\S]*?---/, "").match(/^#\s+(.+)$/m);
  return m ? m[1].trim() : null;
}

/* ---------------------------------------------------------------- evidence */
if (existsSync(DATA_SRC)) {
  const files = walk(DATA_SRC, ".json").filter((p) => dirname(p) === DATA_SRC);
  const keep = new Set();
  for (const src of files) {
    const dst = join(DATA_DST, relative(DATA_SRC, src));
    keep.add(dst);
    writeIfChanged(dst, readFileSync(src));
  }
  prune(DATA_DST, keep, ".json");
  note(`${CHECK ? "checked" : "copied"} ${files.length} evidence files from toolform/advisor/data`);
} else if (IF_PRESENT) {
  note("toolform/advisor/data not found; the committed evidence files in public/data/framework stay");
} else {
  fail("toolform/advisor/data not found (pass --if-present to skip)");
}

/* ---------------------------------------------------------------- docs */
if (existsSync(DOCS_SRC)) {
  const files = walk(DOCS_SRC, ".md");
  const keep = new Set();
  const manifest = [];
  for (const src of files) {
    const rel = relative(DOCS_SRC, src).split("\\").join("/");
    const dst = join(DOCS_DST, rel);
    keep.add(dst);
    const text = readFileSync(src, "utf-8");
    writeIfChanged(dst, text);
    const meta = frontMatter(text);
    const slug = rel.replace(/\.md$/, "");
    manifest.push({
      slug,
      title: meta.title || firstHeading(text) || slug,
      section: meta.section || "Guides",
      order: Number(meta.order ?? 100),
      summary: meta.summary || "",
      path: rel,
    });
  }
  const mpath = join(DOCS_DST, "manifest.json");
  keep.add(mpath);
  writeIfChanged(mpath, JSON.stringify(manifest, null, 2) + "\n");
  prune(DOCS_DST, keep, ".md");
  note(`${CHECK ? "checked" : "copied"} ${files.length} docs from docs/framework`);
} else if (IF_PRESENT) {
  note("docs/framework not found; the docs pages show where the docs come from");
} else {
  fail("docs/framework not found (pass --if-present to skip)");
}

if (problems) {
  console.error(`sync: ${problems} problem${problems === 1 ? "" : "s"}${CHECK ? "; run npm run sync" : ""}`);
  process.exit(1);
}
