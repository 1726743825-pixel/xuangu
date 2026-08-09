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
  showForecast?: boolean;
  emptyMessage?: string;
}

type ForecastPoint = { date: string; value: number; lower: number; upper: number };
type ForecastScenario = { points: ForecastPoint[]; support?: number; resistance?: number };

function formatTurnover(value: number) {
  return `${(value / 100_000_000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 亿`;
}

function nextTradingDates(lastDate: string, count: number) {
  const cursor = new Date(`${lastDate}T00:00:00Z`);
  const dates: string[] = [];
  while (dates.length < count) {
    cursor.setUTCDate(cursor.getUTCDate() + 1);
    if (cursor.getUTCDay() !== 0 && cursor.getUTCDay() !== 6) dates.push(cursor.toISOString().slice(0, 10));
  }
  return dates;
}

function standardDeviation(values: number[]) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length);
}

/** A clearly-labelled five-trading-day technical scenario, not a price target or investment advice. */
function buildForecast(rows: BackendKlineRow[]): ForecastScenario {
  if (rows.length < 20) return { points: [] };
  const sample = rows.slice(-20);
  const closes = sample.map((row) => row[2]);
  const meanX = (closes.length - 1) / 2;
  const meanY = closes.reduce((sum, close) => sum + close, 0) / closes.length;
  const slope = closes.reduce((sum, close, index) => sum + (index - meanX) * (close - meanY), 0)
    / closes.reduce((sum, _, index) => sum + (index - meanX) ** 2, 0);
  const slopeRate = closes.at(-1) ? slope / closes.at(-1)! : 0;
  const returns = closes.slice(1).map((close, index) => close / closes[index] - 1);
  const dailyVolatility = Math.min(0.15, Math.max(0.005, standardDeviation(returns)));
  const range = rows.slice(-60);
  const low60 = Math.min(...range.map((row) => row[3]));
  const high60 = Math.max(...range.map((row) => row[4]));
  const lastClose = rows.at(-1)![2];
  const bucketSize = Math.max((high60 - low60) / 20, lastClose * 0.002);
  const turnoverByPrice = new Map<number, number>();
  range.forEach((row) => {
    const bucket = Math.round(row[2] / bucketSize) * bucketSize;
    turnoverByPrice.set(bucket, (turnoverByPrice.get(bucket) ?? 0) + row[2] * row[5]);
  });
  const densityPrice = Array.from(turnoverByPrice.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] ?? lastClose;
  const support = Math.max(low60, densityPrice <= lastClose ? densityPrice : low60);
  const resistance = Math.min(high60, densityPrice >= lastClose ? densityPrice : high60);
  const points = nextTradingDates(rows.at(-1)![0], 5).map((date, index) => {
    const unconstrained = lastClose * (1 + slopeRate) ** (index + 1);
    const value = Math.min(Math.max(unconstrained, support), resistance);
    const width = value * dailyVolatility * Math.sqrt(index + 1);
    return { date, value, lower: Math.max(support, value - width), upper: Math.min(resistance, value + width) };
  });
  return { points, support, resistance };
}

/** Candlestick chart backed exclusively by API OHLCV rows. */
export function KlineChart({ data, height = 620, className = "", loading = false, showForecast = true, emptyMessage = "暂无 K 线数据" }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const chartData = useMemo(() => {
    const scenario = showForecast ? buildForecast(data) : { points: [] };
    const forecast = scenario.points;
    const dates = [...data.map(([date]) => date), ...forecast.map(({ date }) => date)];
    const spacer = Array(Math.max(data.length - 1, 0)).fill(null);
    return {
      dates,
      candles: [...data.map(([, open, close, low, high]) => [open, close, low, high]), ...forecast.map(() => "-")],
      turnover: data.map(([, , close, , , volume]) => close * volume),
      forecast,
      support: scenario.support,
      resistance: scenario.resistance,
      forecastLine: forecast.length ? [...spacer, data.at(-1)![2], ...forecast.map(({ value }) => value)] : [],
      forecastLower: forecast.length ? [...spacer, data.at(-1)![2], ...forecast.map(({ lower }) => lower)] : [],
      forecastRange: forecast.length ? [...spacer, 0, ...forecast.map(({ lower, upper }) => upper - lower)] : [],
    };
  }, [data, showForecast]);

  useEffect(() => {
    if (!containerRef.current || !data.length) return;
    const isDark = resolvedTheme === "dark";
    const text = isDark ? "#94a3b8" : "#64748b";
    const grid = isDark ? "#1e293b" : "#e2e8f0";
    const series: any[] = [
      {
        name: "历史行情", type: "candlestick", data: chartData.candles,
        itemStyle: { color: "#ef4444", color0: "#10b981", borderColor: "#ef4444", borderColor0: "#10b981" },
        markLine: chartData.forecast.length ? {
          symbol: "none", label: { color: text, fontSize: 10 },
          data: [
            { name: "支撑", yAxis: chartData.support, lineStyle: { type: "dashed", color: "rgba(16,185,129,.75)", opacity: 0.75 } },
            { name: "压力", yAxis: chartData.resistance, lineStyle: { type: "dashed", color: "rgba(239,68,68,.9)", opacity: 0.9 } },
          ],
        } : undefined,
      },
      { name: "成交额（亿）", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: chartData.turnover, barMaxWidth: 12, itemStyle: { color: "#818cf8" } },
    ];
    if (chartData.forecast.length) {
      series.push(
        { name: "波动区间下沿", type: "line", data: chartData.forecastLower, stack: "波动区间", showSymbol: false, lineStyle: { width: 1, type: "dashed", color: "rgba(139,92,246,.45)" }, areaStyle: { color: "transparent" }, silent: true },
        { name: "波动区间", type: "line", data: chartData.forecastRange, stack: "波动区间", showSymbol: false, lineStyle: { width: 1, type: "dashed", color: "rgba(139,92,246,.45)" }, areaStyle: { color: "rgba(139,92,246,.14)" }, silent: true },
        { name: "技术情景预测", type: "line", data: chartData.forecastLine, showSymbol: false, lineStyle: { width: 2.5, color: "rgba(124,58,237,.8)" }, z: 5 },
      );
    }
    const chart = echarts.init(containerRef.current);
    const option: EChartsOption = {
      animation: false,
      backgroundColor: "transparent",
      legend: { type: "scroll", data: ["历史行情", "技术情景预测", "波动区间"], top: 0, left: 4, right: 4, textStyle: { color: text, fontSize: 11 }, selected: { "技术情景预测": chartData.forecast.length > 0, "波动区间": chartData.forecast.length > 0 } },
      tooltip: {
        trigger: "axis", triggerOn: "mousemove|click", confine: true, axisPointer: { type: "cross" },
        formatter: (params: unknown) => {
          const entries = Array.isArray(params) ? params as Array<{ axisValueLabel?: string; seriesName?: string; data?: unknown }> : [];
          const candle = entries.find((entry) => entry.seriesName === "历史行情" && Array.isArray(entry.data))?.data as number[] | undefined;
          const forecast = entries.find((entry) => entry.seriesName === "技术情景预测")?.data as number | null | undefined;
          const lines = [entries[0]?.axisValueLabel ?? ""];
          if (candle) lines.push(`开盘：${candle[0].toFixed(2)}`, `收盘：${candle[1].toFixed(2)}`, `最低：${candle[2].toFixed(2)}`, `最高：${candle[3].toFixed(2)}`, `成交额（亿）：${formatTurnover(candle[1] * (data[chartData.dates.indexOf(entries[0]?.axisValueLabel ?? "")]?.[5] ?? 0))}`);
          if (typeof forecast === "number") lines.push(`技术情景预测：${forecast.toFixed(2)}`, "仅为技术情景，非投资建议");
          return lines.join("<br/>");
        },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      title: [{ text: "成交额（亿）", left: 76, top: "67%", textStyle: { color: text, fontSize: 11, fontWeight: "normal" } }],
      grid: [{ left: 76, right: 24, top: 42, height: "59%", containLabel: true }, { left: 76, right: 24, top: "72%", height: "14%", containLabel: true }],
      xAxis: [0, 1].map((index) => ({ type: "category", data: chartData.dates, boundaryGap: true, gridIndex: index, axisLine: { lineStyle: { color: grid } }, axisLabel: { show: index === 1, color: text, fontSize: 11, hideOverlap: true }, axisTick: { show: false }, splitLine: { show: false } })),
      yAxis: [
        { scale: true, gridIndex: 0, splitArea: { show: true, areaStyle: { color: isDark ? ["rgba(15,23,42,.08)", "rgba(30,41,59,.12)"] : ["rgba(248,250,252,.7)", "rgba(248,250,252,.1)"] } }, axisLabel: { color: text, fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: grid } } },
        { scale: true, gridIndex: 1, name: "成交额（亿）", nameLocation: "middle", nameGap: 48, nameTextStyle: { color: text, fontSize: 11 }, axisLabel: { color: text, fontSize: 11, formatter: (value: number) => `${(value / 100_000_000).toLocaleString("zh-CN", { maximumFractionDigits: 1 })}亿` }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: grid } } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], filterMode: "none", zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: true },
        { type: "slider", xAxisIndex: [0, 1], filterMode: "none", bottom: 2, height: 16, borderColor: "transparent", fillerColor: "rgba(99,102,241,.16)", handleSize: 12, moveHandleSize: 0, brushSelect: false },
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
