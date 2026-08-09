"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { apiUrl, fetcher, getShanghaiToday } from "./api";
import { DashboardFilters } from "./DashboardFilters";
import { MarketIndexCards } from "./MarketIndexCards";
import { Pagination } from "./Pagination";
import { StockTable } from "./StockTable";
import type { MarketIndices, SelectionItem, SelectionPage, StockPage } from "./types";

const PAGE_SIZE = 10;

function compareScoreDescending(a: SelectionItem, b: SelectionItem) {
  if (a.score == null && b.score == null) return a.code.localeCompare(b.code, "zh-CN", { numeric: true });
  if (a.score == null) return 1;
  if (b.score == null) return -1;
  return b.score - a.score || a.code.localeCompare(b.code, "zh-CN", { numeric: true });
}

export function Dashboard() {
  const [date, setDate] = useState(getShanghaiToday);
  const [strategy, setStrategy] = useState("");
  const [industry, setIndustry] = useState("");
  const [page, setPage] = useState(1);

  const selections = useSWR<SelectionPage>(apiUrl(`/api/selections?date=${encodeURIComponent(date)}`), fetcher, {
    keepPreviousData: true,
    revalidateOnFocus: false,
  });
  const stocks = useSWR<StockPage>(apiUrl("/api/stocks?page=1&size=100"), fetcher, {
    revalidateOnFocus: false,
  });
  const indices = useSWR<MarketIndices>(apiUrl("/api/market/indices"), fetcher, {
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
    .sort(compareScoreDescending), [items, strategy, industry]);

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = filteredItems.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const error = selections.error || stocks.error;
  const refreshing = selections.isValidating || stocks.isValidating || indices.isValidating;

  function resetPageAnd<T>(setter: (value: T) => void, value: T) {
    setPage(1);
    setter(value);
  }

  return (
    <main className="min-h-screen overflow-x-hidden bg-slate-50 text-slate-900">
      <div className="mx-auto w-full max-w-[1480px] px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600">
              <span className="h-2 w-2 rounded-full bg-indigo-500" />
              Selection dashboard
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-950">选股结果</h1>
            <p className="mt-2 text-sm text-slate-500">聚合每日选股结果，快速查看价格与评分。</p>
            <p className="mt-2 max-w-4xl text-xs leading-5 text-slate-400">数据来源：AKShare（开源免费接口）｜本系统仅展示公开市场数据与技术指标，不构成任何投资建议。股市有风险，投资需谨慎</p>
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
            onRefresh={() => void Promise.all([selections.mutate(), stocks.mutate(), indices.mutate()])}
          />

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
              数据加载失败，请确认后端服务已启动后重试。
            </div>
          )}

          <MarketIndexCards items={indices.data?.items ?? []} loading={!indices.data && !indices.error} failed={Boolean(indices.error)} />

          <section className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
            <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div>
                <h2 className="font-semibold text-slate-950">股票列表</h2>
                <p className="mt-0.5 text-xs text-slate-400">点击股票名称或整行进入详情</p>
              </div>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500">{filteredItems.length} 条结果</span>
            </div>
            <StockTable items={pageItems} loading={!selections.data && !selections.error} />
            <Pagination page={safePage} pageSize={PAGE_SIZE} total={filteredItems.length} onPageChange={setPage} />
          </section>
        </div>
      </div>
    </main>
  );
}
