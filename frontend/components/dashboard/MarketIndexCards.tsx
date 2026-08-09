import type { MarketIndexItem } from "./types";

const INDEXES = [
  { name: "上证指数", codes: ["000001.SH", "000001"] },
  { name: "深证成指", codes: ["399001.SZ", "399001"] },
  { name: "创业板指", codes: ["399006.SZ", "399006"] },
  { name: "北证50", codes: ["899050.BJ", "899050"] },
  { name: "科创50", codes: ["000688.SH", "000688"] },
] as const;

function formatPrice(value: number | null | undefined) {
  return value == null ? "暂无数据" : value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function findIndex(items: MarketIndexItem[], target: (typeof INDEXES)[number]) {
  return items.find((item) => item.name === target.name || target.codes.some((code) => code === item.code));
}

export function MarketIndexCards({ items, loading, failed }: { items: MarketIndexItem[]; loading: boolean; failed: boolean }) {
  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5" aria-label="主要市场指数">
      {INDEXES.map((target) => {
        const item = findIndex(items, target);
        const change = item?.change_pct;
        const tone = change == null || change === 0 ? "text-slate-500" : change > 0 ? "text-red-500" : "text-emerald-600";
        return (
          <article key={target.name} className="min-w-0 rounded-2xl border border-slate-200/80 bg-white p-4 shadow-sm sm:p-5">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <p className="truncate text-sm font-medium text-slate-600">{target.name}</p>
              <span className="shrink-0 font-mono text-[10px] text-slate-400">{item?.code ?? "—"}</span>
            </div>
            <p className={`mt-3 truncate font-mono text-xl font-bold tracking-tight sm:text-2xl ${item?.price == null ? "text-slate-400" : "text-slate-950"}`}>
              {loading ? "加载中…" : formatPrice(item?.price)}
            </p>
            <div className="mt-2 flex min-w-0 items-center justify-between gap-2 text-xs">
              <span className={`font-mono font-semibold ${tone}`}>{change == null ? "—" : `${change > 0 ? "+" : ""}${change.toFixed(2)}%`}</span>
              <span className="truncate text-right text-[10px] text-slate-400">{failed || !item ? "暂无数据" : item.as_of ?? "更新时间未知"}</span>
            </div>
          </article>
        );
      })}
    </section>
  );
}
