/* Token estimates, the same rule as the Python SDK.
 *
 * toolform.sdk.tokens.estimate_tokens is max(1, round(len(text) / 4)).
 * Python's round() rounds half to even and len() counts code points, so both
 * are reproduced here; otherwise a block of 10 characters would be 3 tokens in
 * the browser and 2 in the CLI.
 */

/** Python's round(): half to even. */
export function roundHalfEven(x: number): number {
  const f = Math.floor(x);
  const diff = x - f;
  if (diff > 0.5) return f + 1;
  if (diff < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/** Length in code points, as Python's len() counts a str. */
export function codePointLength(text: string): number {
  let n = 0;
  for (const _ of text) n++;
  return n;
}

/** About one token per four characters. Always labelled an estimate in the UI. */
export function estimateTokens(text: string): number {
  return Math.max(1, roundHalfEven(codePointLength(text) / 4));
}

export function formatInt(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}
