"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { SelectionItem, SortDirection, SortKey } from "./types";

type StockTableProps = {
  items: SelectionItem[];
  loading: boolean;
  sortKey: SortKey;
  sortDirection: SortDirection;
  onSort: (key: SortKey) => void;
};

const columns: Array<{ key: SortKey; label: string; align?: string }> = [
  { key: "code", label: "代码" },
  { key: "name", label: "名称" },
  { key: "price", label: "现价", align: "text-right" },
  { key: "change_pct", label: "涨跌幅", align: "text-right" },
  { key: "strategy_name", label: "策略信号" },
];

function SortMark({ active, direction }: { active: boolean; direction: SortDirection }) {
  return <span className={active ? "text-indigo-600" : "text-slate-300"}>{active && direction === "desc" ? "↓" : "↑"}</span>;
}

function formatPrice(value: number | null) {
  return value == null ? "—" : value.toFixed(2);
}

function formatChange(value: number | null) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function StockTable({ items, loading, sortKey, sortDirection, onSort }: StockTableProps) {
  const router = useRouter();

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] table-auto border-collapse">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/80">
            {columns.map((column) => (
              <th key={column.key} className={`whitespace-nowrap px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 ${column.align ?? ""}`}>
                <button className="inline-flex items-center gap-1.5 hover:text-slate-900" type="button" onClick={() => onSort(column.key)}>
                  {column.label}
                  <SortMark active={sortKey === column.key} direction={sortDirection} />
                </button>
              </th>
            ))}
            <th className="whitespace-nowrap px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">行业</th>
            <th className="whitespace-nowrap px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {loading ? Array.from({ length: 6 }, (_, index) => (
            <tr key={index} className="animate-pulse">
              <td colSpan={7} className="px-5 py-4"><div className="h-5 rounded bg-slate-100" /></td>
            </tr>
          )) : items.length ? items.map((item) => (
            <tr
              key={`${item.code}-${item.strategy_name}`}
              className="cursor-pointer bg-white transition hover:bg-indigo-50/40 focus-within:bg-indigo-50/40"
              onClick={() => router.push(`/stock/${item.code}`)}
            >
              <td className="whitespace-nowrap px-5 py-4 font-mono text-sm text-slate-500">{item.code}</td>
              <td className="whitespace-nowrap px-5 py-4">
                <Link
                  className="font-semibold text-slate-950 hover:text-indigo-600 hover:underline"
                  href={`/stock/${item.code}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  {item.name}
                </Link>
              </td>
              <td className="whitespace-nowrap px-5 py-4 text-right font-mono text-sm font-medium text-slate-800">{formatPrice(item.price)}</td>
              <td className={`whitespace-nowrap px-5 py-4 text-right font-mono text-sm font-semibold ${item.change_pct == null || item.change_pct === 0 ? "text-slate-500" : item.change_pct > 0 ? "text-red-500" : "text-emerald-600"}`}>
                {formatChange(item.change_pct)}
              </td>
              <td className="px-5 py-4">
                <div className="flex min-w-40 flex-wrap items-center gap-1.5">
                  <span className="rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700">{item.strategy_name}</span>
                  {item.score != null && <span className="text-xs text-slate-400">{item.score.toFixed(0)}分</span>}
                </div>
              </td>
              <td className="max-w-48 truncate px-5 py-4 text-sm text-slate-500" title={item.industry ?? "未分类"}>{item.industry ?? "未分类"}</td>
              <td className="whitespace-nowrap px-5 py-4 text-right">
                <Link
                  className="inline-flex rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                  href={`/stock/${item.code}`}
                  onClick={(event) => event.stopPropagation()}
                >
                  查看详情
                </Link>
              </td>
            </tr>
          )) : (
            <tr>
              <td colSpan={7} className="px-5 py-16 text-center">
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
