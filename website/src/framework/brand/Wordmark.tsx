import { Logo } from "./Logo";

export function Wordmark({ size = 22 }: { size?: number }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--fw-text)" }}>
      <Logo size={size} />
      <span
        style={{
          fontFamily: "var(--fw-display)",
          fontWeight: 600,
          fontSize: size * 0.9,
          letterSpacing: "-0.02em",
          lineHeight: 1,
        }}
      >
        toolform
      </span>
    </span>
  );
}
