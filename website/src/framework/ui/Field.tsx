import { useId, type ReactElement, type ReactNode } from "react";
import { cloneElement } from "react";

/* A labelled form field. The child control gets the id and the hint's id. */
export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactElement }) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className="fw-field">
      <label htmlFor={id}>{label}</label>
      {cloneElement(children, { id, "aria-describedby": hintId })}
      {hint && (
        <div className="hint" id={hintId}>
          {hint}
        </div>
      )}
    </div>
  );
}

/* A group of controls that is not one input: a fieldset with a legend. */
export function FieldGroup({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <fieldset className="fw-field" style={{ border: 0, padding: 0, margin: "0 0 16px" }}>
      <legend className="flabel" style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, padding: 0 }}>
        {label}
      </legend>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </fieldset>
  );
}
