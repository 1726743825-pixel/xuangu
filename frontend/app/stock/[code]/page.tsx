"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { KlineChart, type BackendKlineRow } from "@/components/charts/KlineChart";
import { apiUrl, fetcher } from "@/components/dashboard/api";

type Period = "daily" | "weekly" | "30m";

interface LatestQuote { code: string; name: string; price: number | null; updated_at: string | null; }
interface StockDetail { code: string; name: string; industry: string | null; list_date?: string | null; is_st?: boolean; latest_quote?: LatestQuote | null; }
interface SelectionPerformancePoint { label: "1d" | "3d" | "5d" | "10d" | "25d" | "3m"; target_date: string | null; return_pct: number | null; status: "ok" | "暂无数据"; }
interface SelectionPerformance { trade_date: string; strategy_name: string; base_close: number | null; periods: SelectionPerformancePoint[]; }

const PERIODS: Array<{ value: Period; label: string }> = [{ value: "30m", label: "30分钟" }, { value: "daily", label: "日K" }, { value: "weekly", label: "周K" }];
const PERFORMANCE_HORIZONS: Array<{ horizon: SelectionPerformancePoint["label"]; label: string }> = [
  { horizon: "1d", label: "1 个交易日" }, { horizon: "3d", label: "3 个交易日" }, { horizon: "5d", label: "5 个交易日" },
  { horizon: "10d", label: "10 个交易日" }, { horizon: "25d", label: "25 个交易日" }, { horizon: "3m", label: "3 个月" },
];

function normaliseRows(value: unknown): BackendKlineRow[] {
  if (!Array.isArray(value)) return [];
  const rows: BackendKlineRow[] = [];
  for (const row of value) {
    if (!Array.isArray(row) || row.length !== 6 || typeof row[0] !== "string" || !/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$/.test(row[0])) return [];
    const values = row.slice(1, 6);
    if (!values.every((item) => typeof item === "number" && Number.isFinite(item))) return [];
    const [open, close, low, high, volume] = values as number[];
    if (low > Math.min(open, close) || high < Math.max(open, close) || volume < 0) return [];
    rows.push([row[0], open, close, low, high, volume]);
  }
  return rows;
}
function pctChange(rows: BackendKlineRow[], price: number | null | undefined) {
  const current = price ?? rows.at(-1)?.[2]; const previous = rows.length > 1 ? rows.at(-2)?.[2] : null;
  return current != null && previous != null && previous !== 0 ? (current - previous) / previous * 100 : null;
}

function formatNumber(value: number | null | undefined, digits = 2) { return value == null ? "—" : value.toFixed(digits); }

export default function StockDetailPage({ params }: { params: { code: string } }) {
  const code = params.code.toUpperCase(); const [period, setPeriod] = useState<Period>("daily"); const searchParams = useSearchParams();
  const selectionDate = searchParams.get("date"); const selectionStrategy = searchParams.get("strategy");
  const hasSelectionContext = Boolean(selectionDate && /^\d{4}-\d{2}-\d{2}$/.test(selectionDate) && selectionStrategy);
  const backHref = selectionDate && /^\d{4}-\d{2}-\d{2}$/.test(selectionDate) ? `/?date=${encodeURIComponent(selectionDate)}` : "/";
  const detail = useSWR<StockDetail>(apiUrl(`/api/stock/${encodeURIComponent(code)}/detail`), fetcher, { revalidateOnFocus: false });
  const dailyKline = useSWR<BackendKlineRow[]>(apiUrl(`/api/stock/${encodeURIComponent(code)}/kline?period=daily`), fetcher, { revalidateOnFocus: false });
  const weeklyKline = useSWR<BackendKlineRow[]>(period === "weekly" ? apiUrl(`/api/stock/${encodeURIComponent(code)}/kline?period=weekly`) : null, fetcher, { revalidateOnFocus: false });
  const performanceQuery = hasSelectionContext ? new URLSearchParams({ date: selectionDate!, strategy: selectionStrategy! }) : null;
  const performance = useSWR<SelectionPerformance>(performanceQuery ? apiUrl(`/api/selections/${encodeURIComponent(code)}/performance?${performanceQuery.toString()}`) : null, fetcher, { revalidateOnFocus: false });
  const dailyRows = useMemo(() => normaliseRows(dailyKline.data), [dailyKline.data]);
  const quote = detail.data?.latest_quote; const change = pctChange(dailyRows, quote?.price);
  const performanceByHorizon = new Map(performance.data?.periods.map((item) => [item.label, item]));

  const intradayKline = useSWR<BackendKlineRow[]>(period === "30m" ? apiUrl(`/api/stock/${encodeURIComponent(code)}/kline?period=30m`) : null, fetcher, { revalidateOnFocus: false });
  const visibleRows = useMemo(() => period === "daily" ? dailyRows : period === "weekly" ? normaliseRows(weeklyKline.data) : normaliseRows(intradayKline.data), [period, dailyRows, weeklyKline.data, intradayKline.data]);
  const klineLoading = period === "daily" ? dailyKline.isLoading : period === "weekly" ? weeklyKline.isLoading : intradayKline.isLoading;

  return <main className="min-h-screen overflow-x-hidden bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
    <div className="mx-auto w-full max-w-[1480px] px-4 py-7 sm:px-6 lg:px-8">
      <Link href={backHref} className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 transition hover:text-indigo-600 dark:text-slate-400">← 返回选股结果</Link>
      {detail.error && <div role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">股票详情加载失败，请确认代码与后端服务。</div>}
      <header className="mt-5 rounded-2xl border border-slate-200/80 bg-white px-5 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:px-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div><div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.18em] text-indigo-600"><span className="h-2 w-2 rounded-full bg-indigo-500" />Stock detail</div><div className="flex flex-wrap items-center gap-x-3 gap-y-1"><h1 className="text-2xl font-bold tracking-tight text-slate-950 dark:text-white sm:text-3xl">{detail.data?.name ?? "加载中…"}</h1><span className="font-mono text-sm text-slate-400">{code}</span><span className="text-sm text-slate-500 dark:text-slate-400">{detail.data?.industry ?? "未分类"}</span></div></div>
          <div className="flex items-end gap-3 sm:gap-4"><span className="font-mono text-2xl font-bold tracking-tight text-slate-950 dark:text-white sm:text-3xl">{formatNumber(quote?.price)}</span><span className={`mb-1 font-mono text-sm font-semibold sm:text-base ${change == null || change === 0 ? "text-slate-500" : change > 0 ? "text-red-500" : "text-emerald-600"}`}>{change == null ? "—" : `${change > 0 ? "+" : ""}${change.toFixed(2)}%`}</span></div>
        </div>
      </header>

      <section className="mt-5 rounded-2xl border border-slate-200/80 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="font-semibold text-slate-950 dark:text-white">行情走势</h2><p className="mt-0.5 text-xs text-slate-400">K线 · 成交额</p></div><div className="inline-flex w-fit rounded-lg bg-slate-100 p-1 dark:bg-slate-800">{PERIODS.map((item) => <button key={item.value} type="button" onClick={() => setPeriod(item.value)} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${period === item.value ? "bg-white text-indigo-600 shadow-sm dark:bg-slate-700 dark:text-indigo-300" : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}>{item.label}</button>)}</div></div>
        <div className="p-2 sm:p-4"><KlineChart data={visibleRows} selectionDate={period === "daily" ? selectionDate : null} height={560} showForecast={period === "daily"} loading={klineLoading} emptyMessage={period === "30m" ? "暂无 30 分钟 K 线数据" : "暂无 K 线数据"} /></div>
      </section>

      <section className="mt-5 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><div><h2 className="font-semibold text-slate-950 dark:text-white">入选后表现</h2><p className="mt-0.5 text-xs text-slate-400">以入选日收盘价为基准{performance.data?.trade_date ? ` · 入选日期 ${performance.data.trade_date}` : ""}</p></div><span className="text-xs text-slate-400">未来数据不足时显示暂无数据</span></div>
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">{PERFORMANCE_HORIZONS.map(({ horizon, label }) => { const item = performanceByHorizon.get(horizon); const value = item?.return_pct; return <div key={horizon} className="rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800/60"><p className="text-xs text-slate-500 dark:text-slate-400">{label}</p><p className={`mt-2 font-mono text-lg font-semibold ${value == null ? "text-slate-400" : value >= 0 ? "text-red-500" : "text-emerald-600"}`}>{value == null ? "暂无数据" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`}</p>{item?.target_date && <p className="mt-1 text-[11px] text-slate-400">截至 {item.target_date}</p>}</div>; })}</div>
        {!hasSelectionContext && <p className="mt-4 text-xs text-slate-400">请从选股结果列表进入详情，以读取对应入选日的真实表现。</p>}
      </section>
    </div>
  </main>;
}
