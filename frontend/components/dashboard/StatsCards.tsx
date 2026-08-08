import type { SelectionItem } from "./types";

export function StatsCards({ items }: { items: SelectionItem[] }) {
  const rising = items.filter((item) => (item.change_pct ?? 0) > 0).length;
  const distribution = Object.entries(
    items.reduce<Record<string, number>>((result, item) => {
      result[item.strategy_name] = (result[item.strategy_name] ?? 0) + 1;
      return result;
    }, {}),
  ).sort((a, b) => b[1] - a[1]);

  return (
    <section className="grid gap-4 md:grid-cols-3" aria-label="选股统计">
      <article className="relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
        <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-indigo-50" />
        <p className="relative text-sm text-slate-500">今日选股数</p>
        <div className="relative mt-3 flex items-end gap-2">
          <strong className="text-3xl font-bold tracking-tight text-slate-950">{items.length}</strong>
          <span className="pb-1 text-xs text-slate-400">只股票</span>
        </div>
      </article>

      <article className="relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
        <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-red-50" />
        <p className="relative text-sm text-slate-500">上涨家数</p>
        <div className="relative mt-3 flex items-end gap-2">
          <strong className="text-3xl font-bold tracking-tight text-red-500">{rising}</strong>
          <span className="pb-1 text-xs text-slate-400">
            {items.length ? `占比 ${Math.round((rising / items.length) * 100)}%` : "暂无数据"}
          </span>
        </div>
      </article>

      <article className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm">
        <p className="text-sm text-slate-500">策略分布</p>
        <div className="mt-3 flex min-h-9 flex-wrap items-center gap-2">
          {distribution.length ? distribution.slice(0, 4).map(([name, count]) => (
            <span key={name} className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
              <span className="max-w-28 truncate">{name}</span>
              <b className="text-slate-950">{count}</b>
            </span>
          )) : <span className="text-sm text-slate-400">暂无策略信号</span>}
        </div>
      </article>
    </section>
  );
}
