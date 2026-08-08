import type { HTMLAttributes } from "react";

export type SignalTone = "indigo" | "emerald" | "rose" | "amber" | "sky" | "slate";

export interface SignalTagProps extends HTMLAttributes<HTMLSpanElement> {
  /** Text shown in the badge. */
  label: string;
  /** Semantic colour used to distinguish signals. */
  tone?: SignalTone;
}

const toneClasses: Record<SignalTone, string> = {
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-600/10 dark:bg-indigo-500/15 dark:text-indigo-300 dark:ring-indigo-400/20",
  emerald: "bg-emerald-50 text-emerald-700 ring-emerald-600/10 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-400/20",
  rose: "bg-rose-50 text-rose-700 ring-rose-600/10 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-400/20",
  amber: "bg-amber-50 text-amber-700 ring-amber-600/10 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-400/20",
  sky: "bg-sky-50 text-sky-700 ring-sky-600/10 dark:bg-sky-500/15 dark:text-sky-300 dark:ring-sky-400/20",
  slate: "bg-slate-100 text-slate-600 ring-slate-500/10 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-400/20",
};

export function SignalTag({ label, tone = "indigo", className = "", ...props }: SignalTagProps) {
  return <span className={`inline-flex items-center rounded-md px-2 py-1 text-xs font-semibold ring-1 ring-inset ${toneClasses[tone]} ${className}`} {...props}>{label}</span>;
}
