import type { ReactNode } from "react";

// shadcn-style primitives, hand-written (no CLI). Tone comes from API enums; colours are semantic
// (pass/warn/block/unknown) and deliberately separate from the brand accent.
export type Tone = "pass" | "warn" | "block" | "unknown";

const TONE_CLASS: Record<Tone, string> = {
  pass: "bg-green-100 text-status-pass",
  warn: "bg-amber-100 text-status-warn",
  block: "bg-red-100 text-status-block",
  unknown: "bg-slate-100 text-status-unknown",
};

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}>{children}</span>;
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="rounded border bg-white p-4 shadow-sm">
      {title && <h3 className="mb-2 font-semibold">{title}</h3>}
      {children}
    </div>
  );
}
