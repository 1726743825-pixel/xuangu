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

function strategyBadgeClass(strategyName: string) {
  return strategyName === "超跌"
    ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
    : "bg-indigo-50 text-indigo-700 ring-indigo-200";
}

function numericIndicator(item: SelectionItem, key: string) {
  const value = item.indicators?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textIndicator(item: SelectionItem, key: string) {
  const value = item.indicators?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function displayScore(item: SelectionItem) {
  if (typeof item.display_score === "number" && Number.isFinite(item.display_score)) return item.display_score;
  if (item.strategy_name === "超跌") return numericIndicator(item, "raw_score") ?? item.score;
  return item.score;
}

function scoreText(item: SelectionItem) {
  const value = displayScore(item);
  if (value == null) return "—";
  return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1);
}

function fallbackRatingLevel(item: SelectionItem) {
  const score = displayScore(item);
  if (score == null) return null;
  const max = item.display_score_max ?? numericIndicator(item, "raw_score_max") ?? 100;
  const pct = max > 0 ? score / max : score / 100;
  if (pct >= 0.9) return "S";
  if (pct >= 0.8) return "A";
  if (pct >= 0.65) return "B";
  if (pct >= 0.5) return "C";
  return "D";
}

function ratingLevel(item: SelectionItem) {
  return (item.rating_level ?? textIndicator(item, "rating_level") ?? fallbackRatingLevel(item))?.slice(0, 1).toUpperCase() ?? null;
}

function ratingClass(level: string) {
  switch (level) {
    case "S":
      return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700";
    case "A":
      return "border-orange-200 bg-orange-50 text-orange-700";
    case "B":
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
    case "C":
      return "border-sky-200 bg-sky-50 text-sky-700";
    default:
      return "border-slate-200 bg-slate-50 text-slate-500";
  }
}

function normalizeIndustryText(value: string | null) {
  if (!value) return "未分类";
  const trimmed = value.trim();
  if (!trimmed) return "未分类";
  if (trimmed.includes("|")) {
    return trimmed.split("|").map((item) => item.trim()).filter(Boolean).join(" | ");
  }
  return trimmed
    .replace(/[、，,／/]+/g, " | ")
    .replace(/\s*\|\s*/g, " | ");
}

function detailHref(item: SelectionItem) {
  const query = new URLSearchParams({ date: item.trade_date, strategy: item.strategy_name });
  return `/stock/${encodeURIComponent(item.code)}?${query.toString()}`;
}

export function StockTable({ items, loading }: StockTableProps) {
  const router = useRouter();

  return (
    <div className="max-w-full overflow-x-auto overscroll-x-contain">
      <table className="w-full min-w-[900px] table-fixed border-collapse">
        <colgroup>
          <col className="w-[76px]" />
          <col className="w-[104px]" />
          <col className="w-[84px]" />
          <col className="w-[120px]" />
          <col className="w-[120px]" />
          <col className="w-[120px]" />
          <col className="w-[260px]" />
          <col className="w-[100px]" />
        </colgroup>
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/80">
            <th className="sticky left-0 z-20 whitespace-nowrap bg-slate-50 px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-4">代码</th>
            <th className="sticky left-[76px] z-20 whitespace-nowrap bg-slate-50 px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 sm:px-4">名称</th>
            <th className="whitespace-nowrap px-3 py-3 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">策略</th>
            <th className="whitespace-nowrap px-3 py-3 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">选入当日价格</th>
            <th className="whitespace-nowrap px-3 py-3 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">涨跌幅</th>
            <th className="whitespace-nowrap px-3 py-3 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">总分</th>
            <th className="whitespace-nowrap px-3 py-3 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">行业</th>
            <th className="whitespace-nowrap px-3 py-3 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {loading ? Array.from({ length: 6 }, (_, index) => (
            <tr key={index} className="animate-pulse">
              <td colSpan={8} className="px-5 py-4"><div className="h-5 rounded bg-slate-100" /></td>
            </tr>
          )) : items.length ? items.map((item) => {
            const level = ratingLevel(item);
            const industry = normalizeIndustryText(item.industry);
            return (
            <tr
              key={`${item.code}-${item.strategy_name}`}
              className="cursor-pointer bg-white transition hover:bg-indigo-50/40 focus-within:bg-indigo-50/40"
              onClick={() => router.push(detailHref(item))}
            >
              <td className="sticky left-0 z-10 whitespace-nowrap bg-white px-3 py-4 font-mono text-sm text-slate-500 sm:px-4">{item.code}</td>
              <td className="sticky left-[76px] z-10 min-w-0 bg-white px-3 py-4 sm:px-4">
                <Link
                  className="block truncate font-semibold text-slate-950 hover:text-indigo-600 hover:underline"
                  href={detailHref(item)}
                  onClick={(event) => event.stopPropagation()}
                  title={item.name}
                >
                  {item.name}
                </Link>
              </td>
              <td className="whitespace-nowrap px-3 py-4 text-center">
                <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${strategyBadgeClass(item.strategy_name)}`}>
                  {item.strategy_name}
                </span>
              </td>
              <td className="whitespace-nowrap px-3 py-4 text-center font-mono text-sm font-medium text-slate-800">{formatPrice(item.selection_price)}</td>
              <td className={`whitespace-nowrap px-3 py-4 text-center font-mono text-sm font-semibold ${item.change_pct == null || item.change_pct === 0 ? "text-slate-500" : item.change_pct > 0 ? "text-red-500" : "text-emerald-600"}`}>
                {formatChange(item.change_pct)}
              </td>
              <td className="whitespace-nowrap px-3 py-4 text-center">
                <span className="inline-flex items-center justify-center gap-1.5 font-mono text-sm font-semibold text-slate-700">
                  {scoreText(item)}
                  {level && <span className={`inline-flex h-5 min-w-5 items-center justify-center rounded border px-1 text-[11px] font-bold leading-none ${ratingClass(level)}`}>{level}</span>}
                </span>
              </td>
              <td className="truncate px-3 py-4 text-center text-sm text-slate-500" title={industry}>{industry}</td>
              <td className="whitespace-nowrap px-3 py-4 text-center">
                <Link
                  className="inline-flex rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600"
                  href={detailHref(item)}
                  onClick={(event) => event.stopPropagation()}
                >
                  查看详情
                </Link>
              </td>
            </tr>
          ); }) : (
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
