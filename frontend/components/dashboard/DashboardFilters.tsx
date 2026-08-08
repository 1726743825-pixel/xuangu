type DashboardFiltersProps = {
  date: string;
  strategy: string;
  industry: string;
  strategies: string[];
  industries: string[];
  refreshing: boolean;
  onDateChange: (date: string) => void;
  onStrategyChange: (strategy: string) => void;
  onIndustryChange: (industry: string) => void;
  onRefresh: () => void;
};

const fieldClass =
  "h-11 min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 shadow-sm outline-none transition focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100";

export function DashboardFilters({
  date,
  strategy,
  industry,
  strategies,
  industries,
  refreshing,
  onDateChange,
  onStrategyChange,
  onIndustryChange,
  onRefresh,
}: DashboardFiltersProps) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[180px_minmax(180px,1fr)_minmax(180px,1fr)_auto]">
        <label className="grid gap-1.5 text-xs font-medium text-slate-500">
          交易日期
          <input
            aria-label="交易日期"
            className={fieldClass}
            type="date"
            value={date}
            onChange={(event) => onDateChange(event.target.value)}
          />
        </label>
        <label className="grid gap-1.5 text-xs font-medium text-slate-500">
          策略
          <select
            aria-label="策略筛选"
            className={fieldClass}
            value={strategy}
            onChange={(event) => onStrategyChange(event.target.value)}
          >
            <option value="">全部策略</option>
            {strategies.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs font-medium text-slate-500">
          行业
          <select
            aria-label="行业筛选"
            className={fieldClass}
            value={industry}
            onChange={(event) => onIndustryChange(event.target.value)}
          >
            <option value="">全部行业</option>
            {industries.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <button
          className="mt-auto inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-slate-950 px-5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-600 disabled:cursor-wait disabled:opacity-60"
          disabled={refreshing}
          onClick={onRefresh}
          type="button"
        >
          <svg className={refreshing ? "h-4 w-4 animate-spin" : "h-4 w-4"} viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {refreshing ? "刷新中" : "刷新数据"}
        </button>
      </div>
    </section>
  );
}
