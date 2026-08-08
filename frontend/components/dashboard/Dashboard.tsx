"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { apiUrl, fetcher, getLatestTradingDate } from "./api";
import { DashboardFilters } from "./DashboardFilters";
import { Pagination } from "./Pagination";
import { StatsCards } from "./StatsCards";
import { StockTable } from "./StockTable";
import type { SelectionItem, SelectionPage, SortDirection, SortKey, StockPage } from "./types";

const PAGE_SIZE = 10;

function compareValues(a: SelectionItem, b: SelectionItem, key: SortKey) {
  const left = a[key];
  const right = b[key];
  if (left == null) return 1;
  if (right == null) return -1;
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right), "zh-CN", { numeric: true });
}

export function Dashboard() {
  const [date, setDate] = useState(getLatestTradingDate);
  const [strategy, setStrategy] = useState("");
  const [industry, setIndustry] = useState("");
  const [page, setPage] = useState(1);
  const [sortKey, setSortKey] = useState<SortKey>("change_pct");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const selections = useSWR<SelectionPage>(apiUrl(`/api/selections?date=${encodeURIComponent(date)}`), fetcher, {
    keepPreviousData: true,
    revalidateOnFocus: false,
  });
  const stocks = useSWR<StockPage>(apiUrl("/api/stocks?page=1&size=100"), fetcher, {
    revalidateOnFocus: false,
  });

  const items = selections.data?.items ?? [];
  const strategies = useMemo(() => Array.from(new Set(items.map((item) => item.strategy_name))).sort((a, b) => a.localeCompare(b, "zh-CN")), [items]);
  const industries = useMemo(() => Array.from(new Set([
    ...items.map((item) => item.industry),
    ...(stocks.data?.items ?? []).map((item) => item.industry),
  ].filter((item): item is string => Boolean(item)))).sort((a, b) => a.localeCompare(b, "zh-CN")), [items, stocks.data]);

  const filteredItems = useMemo(() => items
    .filter((item) => !strategy || item.strategy_name === strategy)
    .filter((item) => !industry || item.industry === industry)
    .sort((a, b) => compareValues(a, b, sortKey) * (sortDirection === "asc" ? 1 : -1)), [items, strategy, industry, sortKey, sortDirection]);

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = filteredItems.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const error = selections.error || stocks.error;
  const refreshing = selections.isValidating || stocks.isValidating;

  function resetPageAnd<T>(setter: (value: T) => void, value: T) {
    setPage(1);
    setter(value);
  }

  function handleSort(key: SortKey) {
    setPage(1);
    if (key === sortKey) setSortDirection((current) => current === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDirection(key === "name" || key === "code" || key === "strategy_name" ? "asc" : "desc");
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto w-full max-w-[1480px] px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600">
              <span className="h-2 w-2 rounded-full bg-indigo-500" />
              Selection dashboard
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-950">选股结果</h1>
            <p className="mt-2 text-sm text-slate-500">聚合每日策略信号，快速定位值得关注的股票。</p>
          </div>
          <p className="text-xs text-slate-400">数据日期 · {date}</p>
        </header>

        <div className="space-y-5">
          <DashboardFilters
            date={date}
            strategy={strategy}
            industry={industry}
            strategies={strategies}
            industries={industries}
            refreshing={refreshing}
            onDateChange={(value) => resetPageAnd(setDate, value)}
            onStrategyChange={(value) => resetPageAnd(setStrategy, value)}
            onIndustryChange={(value) => resetPageAnd(setIndustry, value)}
            onRefresh={() => void Promise.all([selections.mutate(), stocks.mutate()])}
          />

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
              数据加载失败，请确认后端服务已启动后重试。
            </div>
          )}

          <StatsCards items={items} />

          <section className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
            <div className="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div>
                <h2 className="font-semibold text-slate-950">股票列表</h2>
                <p className="mt-0.5 text-xs text-slate-400">点击股票名称或整行进入详情</p>
              </div>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500">{filteredItems.length} 条结果</span>
            </div>
            <StockTable items={pageItems} loading={!selections.data && !selections.error} sortKey={sortKey} sortDirection={sortDirection} onSort={handleSort} />
            <Pagination page={safePage} pageSize={PAGE_SIZE} total={filteredItems.length} onPageChange={setPage} />
          </section>
        </div>
      </div>
    </main>
  );
}
