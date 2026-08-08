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

/** Candlestick chart backed exclusively by API OHLCV rows. */
export function KlineChart({ data, height = 620, className = "", loading = false }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const chartData = useMemo(() => {
    const dates = data.map(([date]) => date);
    return { dates, candles: data.map(([, open, close, low, high]) => [open, close, low, high]), volume: data.map(([, open, close, , , volume]) => ({ value: volume, itemStyle: { color: close >= open ? "#ef4444" : "#10b981" } })) };
  }, [data]);

  useEffect(() => {
    if (!containerRef.current || !data.length) return;
    const isDark = resolvedTheme === "dark"; const text = isDark ? "#94a3b8" : "#64748b"; const grid = isDark ? "#1e293b" : "#e2e8f0";
    const chart = echarts.init(containerRef.current);
    const option: EChartsOption = {
      animation: false, backgroundColor: "transparent", tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      grid: [{ left: 54, right: 20, top: 26, height: "62%" }, { left: 54, right: 20, top: "73%", height: "17%" }],
      xAxis: [0, 1].map((index) => ({ type: "category", data: chartData.dates, boundaryGap: true, gridIndex: index, axisLine: { lineStyle: { color: grid } }, axisLabel: { show: index === 1, color: text, fontSize: 11 }, axisTick: { show: false }, splitLine: { show: false } })),
      yAxis: [0, 1].map((index) => ({ scale: true, gridIndex: index, splitArea: { show: true, areaStyle: { color: isDark ? ["rgba(15,23,42,.08)", "rgba(30,41,59,.12)"] : ["rgba(248,250,252,.7)", "rgba(248,250,252,.1)"] } }, axisLabel: { color: text, fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: grid } } })),
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: Math.max(0, 100 - Math.min(100, 12000 / Math.max(data.length, 1))), end: 100 }, { type: "slider", xAxisIndex: [0, 1], bottom: 2, height: 16, borderColor: "transparent", fillerColor: "rgba(99,102,241,.15)", handleSize: 0 }],
      series: [
        { name: "日K", type: "candlestick", data: chartData.candles, itemStyle: { color: "#ef4444", color0: "#10b981", borderColor: "#ef4444", borderColor0: "#10b981" } },
        { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: chartData.volume, barMaxWidth: 12 },
      ],
    };
    chart.setOption(option); const observer = new ResizeObserver(() => chart.resize()); observer.observe(containerRef.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [chartData, data.length, resolvedTheme]);

  if (loading) return <div style={{ height }} className={`animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800 ${className}`} />;
  if (!data.length) return <div style={{ height }} className={`flex items-center justify-center rounded-xl bg-slate-50 text-sm text-slate-400 dark:bg-slate-950 ${className}`}>暂无 K 线数据</div>;
  return <div ref={containerRef} style={{ height }} className={`w-full ${className}`} role="img" aria-label="股票 K 线与成交量图表" />;
}
