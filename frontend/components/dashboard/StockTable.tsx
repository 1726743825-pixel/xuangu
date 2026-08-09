"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { SelectionItem } from "./types";

type StockTableProps = {
  items: SelectionItem[];
  loading: boolean;
};

function formatPrice(value: number | null) {
  return value == null ? "—" : value.toFixed(2);
}

function formatChange(value: number | null) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function detailHref(item: SelectionItem) {
  const query = new URLSearchParams({ date: item.trade_date, strategy: item.strategy_name });
  return `/stock/${encodeURIComponent(item.code)}?${query.toString()}`;
}

export function StockTable({ items, loading }: StockTableProps) {
  const router = useRouter();

  return (
    <div className="max-w-full overflow-x-auto overscroll-x-contain">
      <table className="w-full min-w-[1060px] table-auto border-collapse">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/80">
            <th className="sticky left-0 z-20 w-[76px] min-w-[76px] whitespace-nowrap bg-slate-50 px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">代码</th>
            <th className="sticky left-[76px] z-20 min-w-[132px] whitespace-nowrap bg-slate-50 px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">名称</th>
            <th className="whitespace-nowrap px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">选入当日价格</th>
            <th className="whitespace-nowrap px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">当前价格</th>
            <th className="whitespace-nowrap px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">涨跌幅</th>
            <th className="whitespace-nowrap px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">总分</th>
            <th className="whitespace-nowrap px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">行业</th>
            <th className="whitespace-nowrap px-3 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-5">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {loading ? Array.from({ length: 6 }, (_, index) => (
            <tr key={index} className="animate-pulse">
              <td colSpan={8} className="px-5 py-4"><div className="h-5 rounded bg-slate-100" /></td>
            </tr>
          )) : items.length ? items.map((item) => (
            <tr
              key={`${item.code}-${item.strategy_name}`}
              className="cursor-pointer bg-white transition hover:bg-indigo-50/40 focus-within:bg-indigo-50/40"
              onClick={() => router.push(detailHref(item))}
            >
              <td className="sticky left-0 z-10 w-[76px] min-w-[76px] whitespace-nowrap bg-white px-3 py-4 font-mono text-sm text-slate-500 sm:px-5">{item.code}</td>
              <td className="sticky left-[76px] z-10 min-w-[132px] whitespace-nowrap bg-white px-3 py-4 sm:px-5">
                <Link
                  className="font-semibold text-slate-950 hover:text-indigo-600 hover:underline"
                  href={detailHref(item)}
                  onClick={(event) => event.stopPropagation()}
                >
                  {item.name}
                </Link>
              </td>
              <td className="whitespace-nowrap px-3 py-4 text-right sm:px-5"><div className="font-mono text-sm font-medium text-slate-800">{formatPrice(item.selection_price)}</div><div className="mt-0.5 text-[10px] text-slate-400">{item.selection_price_date ?? "—"}</div></td>
              <td className="whitespace-nowrap px-3 py-4 text-right sm:px-5"><div className="font-mono text-sm font-medium text-slate-800">{formatPrice(item.current_price)}</div><div className="mt-0.5 max-w-32 truncate text-[10px] text-slate-400" title={item.current_price_as_of ?? undefined}>{item.current_price_as_of ?? "—"}</div></td>
              <td className={`whitespace-nowrap px-3 py-4 text-right font-mono text-sm font-semibold sm:px-5 ${item.change_pct == null || item.change_pct === 0 ? "text-slate-500" : item.change_pct > 0 ? "text-red-500" : "text-emerald-600"}`}>
                {formatChange(item.change_pct)}
              </td>
              <td className="whitespace-nowrap px-3 py-4 text-right font-mono text-sm font-semibold text-slate-700 sm:px-5">{item.score == null ? "—" : item.score.toFixed(0)}</td>
              <td className="max-w-48 truncate px-3 py-4 text-sm text-slate-500 sm:px-5" title={item.industry ?? "未分类"}>{item.industry ?? "未分类"}</td>
              <td className="whitespace-nowrap px-3 py-4 text-right sm:px-5">
                <Link
                  className="inline-flex rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                  href={detailHref(item)}
                  onClick={(event) => event.stopPropagation()}
                >
                  查看详情
                </Link>
              </td>
            </tr>
          )) : (
            <tr>
              <td colSpan={8} className="px-5 py-16 text-center">
                <p className="font-medium text-slate-700">没有找到选股结果</p>
                <p className="mt-1 text-sm text-slate-400">请调整日期或筛选条件后重试</p>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
