"use client";

import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { useTheme } from "next-themes";

/** Exact tuple returned by backend `GET /api/stock/{code}/kline`: date, open, close, low, high, volume. */
export type BackendKlineRow = [date: string, open: number, close: number, low: number, high: number, volume: number];

export interface KlineChartProps {
  data: BackendKlineRow[];
  height?: number;
  className?: string;
  loading?: boolean;
}

type MacdValue = { dif: number; dea: number; histogram: number };
const average = (values: number[], period: number, index: number) => index + 1 < period ? null : values.slice(index + 1 - period, index + 1).reduce((sum, value) => sum + value, 0) / period;

function calculateMacd(closes: number[]): MacdValue[] {
  let ema12 = closes[0] ?? 0; let ema26 = closes[0] ?? 0; let dea = 0;
  return closes.map((close) => { ema12 = ema12 * 11 / 13 + close * 2 / 13; ema26 = ema26 * 25 / 27 + close * 2 / 27; const dif = ema12 - ema26; dea = dea * 8 / 10 + dif * 2 / 10; return { dif, dea, histogram: (dif - dea) * 2 }; });
}

/** Candlestick chart with volume and MACD subcharts. */
export function KlineChart({ data, height = 620, className = "", loading = false }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const chartData = useMemo(() => {
    const dates = data.map(([date]) => date); const closes = data.map(([, , close]) => close); const macd = calculateMacd(closes);
    return { dates, candles: data.map(([, open, close, low, high]) => [open, close, low, high]), volume: data.map(([, open, close, , , volume]) => ({ value: volume, itemStyle: { color: close >= open ? "#ef4444" : "#10b981" } })), ma5: closes.map((_, index) => average(closes, 5, index)), ma10: closes.map((_, index) => average(closes, 10, index)), macd };
  }, [data]);

  useEffect(() => {
    if (!containerRef.current || !data.length) return;
    const isDark = resolvedTheme === "dark"; const text = isDark ? "#94a3b8" : "#64748b"; const grid = isDark ? "#1e293b" : "#e2e8f0";
    const chart = echarts.init(containerRef.current);
    const option: EChartsOption = {
      animation: false, backgroundColor: "transparent", tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      grid: [{ left: 54, right: 20, top: 26, height: "48%" }, { left: 54, right: 20, top: "60%", height: "13%" }, { left: 54, right: 20, top: "80%", height: "13%" }],
      xAxis: [0, 1, 2].map((index) => ({ type: "category", data: chartData.dates, boundaryGap: true, gridIndex: index, axisLine: { lineStyle: { color: grid } }, axisLabel: { show: index === 2, color: text, fontSize: 11 }, axisTick: { show: false }, splitLine: { show: false } })),
      yAxis: [0, 1, 2].map((index) => ({ scale: true, gridIndex: index, splitArea: { show: true, areaStyle: { color: isDark ? ["rgba(15,23,42,.08)", "rgba(30,41,59,.12)"] : ["rgba(248,250,252,.7)", "rgba(248,250,252,.1)"] } }, axisLabel: { color: text, fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: grid } } })),
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1, 2], start: Math.max(0, 100 - Math.min(100, 12000 / Math.max(data.length, 1))), end: 100 }, { type: "slider", xAxisIndex: [0, 1, 2], bottom: 2, height: 16, borderColor: "transparent", fillerColor: "rgba(99,102,241,.15)", handleSize: 0 }],
      series: [
        { name: "日K", type: "candlestick", data: chartData.candles, itemStyle: { color: "#ef4444", color0: "#10b981", borderColor: "#ef4444", borderColor0: "#10b981" } },
        { name: "MA5", type: "line", data: chartData.ma5, smooth: true, showSymbol: false, lineStyle: { width: 1.3, color: "#6366f1" } },
        { name: "MA10", type: "line", data: chartData.ma10, smooth: true, showSymbol: false, lineStyle: { width: 1.3, color: "#f59e0b" } },
        { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: chartData.volume, barMaxWidth: 12 },
        { name: "MACD", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: chartData.macd.map(({ histogram }) => ({ value: histogram, itemStyle: { color: histogram >= 0 ? "#ef4444" : "#10b981" } })), barMaxWidth: 12 },
        { name: "DIF", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: chartData.macd.map(({ dif }) => dif), showSymbol: false, lineStyle: { width: 1.2, color: "#6366f1" } },
        { name: "DEA", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: chartData.macd.map(({ dea }) => dea), showSymbol: false, lineStyle: { width: 1.2, color: "#f59e0b" } },
      ],
    };
    chart.setOption(option); const observer = new ResizeObserver(() => chart.resize()); observer.observe(containerRef.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [chartData, data.length, resolvedTheme]);

  if (loading) return <div style={{ height }} className={`animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800 ${className}`} />;
  if (!data.length) return <div style={{ height }} className={`flex items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-400 dark:bg-slate-950 ${className}`}>暂无 K 线数据</div>;
  return <div ref={containerRef} style={{ height }} className={`w-full ${className}`} role="img" aria-label="股票 K 线、成交量和 MACD 图表" />;
}
