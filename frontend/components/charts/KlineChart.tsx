"use client";

import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { useTheme } from "next-themes";
import { buildKlineModel, buildKlineSeries, type BackendKlineRow } from "./klineModel";

export type { BackendKlineRow } from "./klineModel";

export interface KlineChartProps {
  data: BackendKlineRow[];
  selectionDate?: string | null;
  height?: number;
  className?: string;
  loading?: boolean;
  showForecast?: boolean;
  emptyMessage?: string;
}

function formatTurnover(value: number) {
  return `${(value / 100_000_000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 亿`;
}

function dailyCloseChange(rows: BackendKlineRow[], index: number) {
  if (index <= 0 || index >= rows.length) return null;
  const previousClose = rows[index - 1]?.[2];
  const currentClose = rows[index]?.[2];
  if (!previousClose || !currentClose) return null;
  return (currentClose / previousClose - 1) * 100;
}

/** Candlestick chart backed exclusively by API OHLCV rows. */
export function KlineChart({ data, selectionDate, height = 620, className = "", loading = false, showForecast = true, emptyMessage = "暂无 K 线数据" }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const chartData = useMemo(() => buildKlineModel(data, showForecast, selectionDate), [data, showForecast, selectionDate]);

  useEffect(() => {
    if (!containerRef.current || !data.length) return;
    const isDark = resolvedTheme === "dark";
    const text = isDark ? "#94a3b8" : "#64748b";
    const grid = isDark ? "#1e293b" : "#e2e8f0";
    const series = buildKlineSeries(chartData);
    const chart = echarts.init(containerRef.current);
    const option: EChartsOption = {
      animation: false,
      backgroundColor: "transparent",
      legend: { type: "scroll", data: ["历史行情", "布林上轨", "布林中轨", "布林下轨", "技术情景预测", "预测区间"], top: 0, left: 4, right: 4, textStyle: { color: text, fontSize: 11 } },
      tooltip: {
        trigger: "axis", triggerOn: "mousemove|click", confine: true, axisPointer: { type: "cross" },
        formatter: (params: unknown) => {
          const entries = Array.isArray(params) ? params as Array<{ axisValueLabel?: string; seriesName?: string; data?: unknown; dataIndex?: number }> : [];
          const candleEntry = entries.find((entry) => entry.seriesName === "历史行情" && typeof entry.dataIndex === "number");
          const dataIndex = candleEntry?.dataIndex ?? chartData.dates.indexOf(entries[0]?.axisValueLabel ?? "");
          const row = dataIndex >= 0 && dataIndex < data.length ? data[dataIndex] : undefined;
          const forecast = entries.find((entry) => entry.seriesName === "技术情景预测")?.data as number | null | undefined;
          const lines = [entries[0]?.axisValueLabel ?? ""];
          if (row) {
            const [, open, close, low, high, volume] = row;
            const change = dailyCloseChange(data, dataIndex);
            const changeLabel = change == null || change >= 0 ? "涨幅" : "跌幅";
            const changeColor = change == null || change >= 0 ? "#ef4444" : "#10b981";
            lines.push(
              `开盘：${open.toFixed(2)}`,
              `收盘：${close.toFixed(2)}`,
              change == null ? `${changeLabel}：—` : `<span style="color:${changeColor};font-weight:600">${changeLabel}：${Math.abs(change).toFixed(2)}%</span>`,
              `最低：${low.toFixed(2)}`,
              `最高：${high.toFixed(2)}`,
              `成交额（亿）：${formatTurnover(close * volume)}`,
            );
          }
          if (typeof forecast === "number") lines.push(`技术情景预测：${forecast.toFixed(2)}`, "仅为技术情景，非投资建议");
          return lines.join("<br/>");
        },
      },
      axisPointer: { link: [{ xAxisIndex: [0, 1] }], snap: true },
      title: [{ text: "成交额（亿）", left: 76, top: "67%", textStyle: { color: text, fontSize: 11, fontWeight: "normal" } }],
      grid: [{ left: 76, right: 34, top: 42, height: "59%", containLabel: false }, { left: 76, right: 34, top: "72%", height: "14%", containLabel: false }],
      xAxis: [0, 1].map((index) => ({ type: "category", data: chartData.dates, boundaryGap: true, gridIndex: index, axisPointer: { snap: true }, axisLine: { lineStyle: { color: grid } }, axisLabel: { show: index === 1, color: text, fontSize: 11, hideOverlap: true }, axisTick: { show: false }, splitLine: { show: false } })),
      yAxis: [
        { scale: true, min: chartData.priceMin, max: chartData.priceMax, gridIndex: 0, splitArea: { show: true, areaStyle: { color: isDark ? ["rgba(15,23,42,.08)", "rgba(30,41,59,.12)"] : ["rgba(248,250,252,.7)", "rgba(248,250,252,.1)"] } }, axisLabel: { color: text, fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: grid } } },
        { scale: true, gridIndex: 1, name: "成交额（亿）", nameLocation: "middle", nameGap: 48, nameTextStyle: { color: text, fontSize: 11 }, axisLabel: { color: text, fontSize: 11, formatter: (value: number) => `${(value / 100_000_000).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}亿` }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: grid } } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], filterMode: "none", start: 0, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: true },
        { type: "slider", xAxisIndex: [0, 1], filterMode: "none", start: 0, end: 100, bottom: 2, height: 16, borderColor: "transparent", fillerColor: "rgba(99,102,241,.16)", handleSize: 12, moveHandleSize: 0, brushSelect: false },
      ],
      series: series as never,
    };
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(containerRef.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [chartData, data, resolvedTheme]);

  if (loading) return <div style={{ height }} className={`animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800 ${className}`} />;
  if (!data.length) return <div style={{ height }} className={`flex items-center justify-center rounded-xl bg-slate-50 px-6 text-center text-sm text-slate-400 dark:bg-slate-950 ${className}`}>{emptyMessage}</div>;
  return <div ref={containerRef} style={{ height, touchAction: "none" }} className={`w-full ${className}`} role="img" aria-label="股票 K 线、成交额与技术情景预测图表" />;
}
