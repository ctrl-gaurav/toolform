/* The mark: "the ladder". Four bars, 25 to 100% long, for the four rungs of
 * the study's schema ladder: names, parameter names, types, the full schema.
 * The longest bar, the full schema, takes the accent. */

export function Logo({ size = 24, title }: { size?: number; title?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      {title && <title>{title}</title>}
      <rect x="2" y="3" width="5" height="3" rx="1.5" fill="currentColor" />
      <rect x="2" y="8" width="10" height="3" rx="1.5" fill="currentColor" />
      <rect x="2" y="13" width="15" height="3" rx="1.5" fill="currentColor" />
      <rect x="2" y="18" width="20" height="3" rx="1.5" fill="var(--fw-accent, #4FE3C1)" />
    </svg>
  );
}
