import { useState } from "react";

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older browsers and http origins: fall back to a hidden textarea.
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

export function CopyButton({ text, label = "Copy", className = "fw-copy" }: { text: string; label?: string; className?: string }) {
  const [state, setState] = useState<"idle" | "done" | "fail">("idle");
  return (
    <button
      type="button"
      className={className}
      onClick={async () => {
        const ok = await copyText(text);
        setState(ok ? "done" : "fail");
        window.setTimeout(() => setState("idle"), 1400);
      }}
      aria-live="polite"
    >
      {state === "done" ? "Copied" : state === "fail" ? "Copy failed" : label}
    </button>
  );
}
