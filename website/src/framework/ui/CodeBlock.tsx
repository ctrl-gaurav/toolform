import { CopyButton } from "./CopyButton";

/* A code block with a title bar and a copy button. Highlighting is a light
 * pass for Python, shell and JSON only: comments, strings, keywords and
 * numbers, so the code reads well without a highlighter library. */

const KEYWORDS: Record<string, string[]> = {
  python: ["from", "import", "def", "return", "for", "in", "if", "else", "as", "with", "print", "None", "True", "False", "lambda", "class"],
  bash: ["pip", "toolform", "curl", "npm", "cd", "python"],
};

function esc(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function highlight(code: string, lang?: string): string {
  if (!lang || !["python", "py", "bash", "sh", "shell", "json", "console"].includes(lang)) return esc(code);
  const l = lang === "py" ? "python" : ["sh", "shell", "console"].includes(lang) ? "bash" : lang;
  const kw = KEYWORDS[l] ?? [];
  const re = new RegExp(
    [
      l === "json" ? "(?!)" : "(#[^\\n]*)",
      `("(?:[^"\\\\\\n]|\\\\.)*"|'(?:[^'\\\\\\n]|\\\\.)*')`,
      kw.length ? `\\b(${kw.join("|")})\\b` : "(?!)",
      "\\b(\\d+(?:\\.\\d+)?)\\b",
    ].join("|"),
    "g",
  );
  let out = "";
  let last = 0;
  for (const m of code.matchAll(re)) {
    out += esc(code.slice(last, m.index));
    const [whole, c, s, k, n] = m;
    const cls = c ? "tok-c" : s ? "tok-s" : k ? "tok-k" : n ? "tok-n" : "";
    out += `<span class="${cls}">${esc(whole)}</span>`;
    last = (m.index ?? 0) + whole.length;
  }
  return out + esc(code.slice(last));
}

export function CodeBlock({ code, lang, title, wrap, tall, copy = true }: { code: string; lang?: string; title?: string; wrap?: boolean; tall?: boolean; copy?: boolean }) {
  return (
    <div className={`fw-code${tall ? " tall" : ""}`}>
      {(title || copy) && (
        <div className="fw-code-bar">
          <span>{title ?? lang ?? ""}</span>
          {copy && <CopyButton text={code} />}
        </div>
      )}
      <pre className={wrap ? "wrapped" : undefined} tabIndex={0}>
        <code dangerouslySetInnerHTML={{ __html: highlight(code, lang) }} />
      </pre>
    </div>
  );
}
