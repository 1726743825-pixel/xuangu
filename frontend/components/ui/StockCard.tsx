import Link from "next/link";
import { SignalTag, type SignalTone } from "./SignalTag";

export interface StockCardProps {
  code: string;
  name: string;
  price?: number | null;
  changePct?: number | null;
  industry?: string | null;
  signals?: Array<{ label: string; tone?: SignalTone }>;
  href?: string;
  className?: string;
}

function Change({ value }: { value?: number | null }) {
  if (value == null) return <span className="font-mono text-sm text-slate-400">—</span>;
  const colour = value === 0 ? "text-slate-500" : value > 0 ? "text-red-500" : "text-emerald-600";
  return <span className={`font-mono text-sm font-semibold ${colour}`}>{value > 0 ? "+" : ""}{value.toFixed(2)}%</span>;
}

/** Compact stock summary card for use outside the stock detail page. */
export function StockCard({ code, name, price, changePct, industry, signals = [], href, className = "" }: StockCardProps) {
  const content = <>
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0"><p className="truncate font-semibold text-slate-950 dark:text-white">{name}</p><p className="mt-0.5 font-mono text-xs text-slate-400">{code}</p></div>
      <Change value={changePct} />
    </div>
    <div className="mt-4 flex items-end justify-between gap-3"><span className="font-mono text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">{price == null ? "—" : price.toFixed(2)}</span><span className="truncate text-xs text-slate-500 dark:text-slate-400">{industry ?? "未分类"}</span></div>
    {signals.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{signals.map((signal) => <SignalTag key={signal.label} {...signal} />)}</div>}
  </>;
  const classes = `block rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm transition hover:border-indigo-200 hover:shadow-md dark:border-slate-800 dark:bg-slate-900 ${className}`;
  return href ? <Link href={href} className={classes}>{content}</Link> : <article className={classes}>{content}</article>;
}
