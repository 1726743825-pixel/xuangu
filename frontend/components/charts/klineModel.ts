/** Strict backend tuple: date, open, close, low, high, volume. */
export type BackendKlineRow = [date: string, open: number, close: number, low: number, high: number, volume: number];

type ForecastPoint = { date: string; value: number; lower: number; upper: number };
type ForecastScenario = { points: ForecastPoint[]; support?: number; resistance?: number };
type NullableNumber = number | null;
type TurnoverBar = { value: number | null; itemStyle?: { color: string } };

export type KlineModel = {
  dates: string[];
  candles: Array<number[] | string>;
  turnover: TurnoverBar[];
  forecast: ForecastPoint[];
  support?: number;
  resistance?: number;
  bollingerUpper: NullableNumber[];
  bollingerMiddle: NullableNumber[];
  bollingerLower: NullableNumber[];
  forecastLine: NullableNumber[];
  forecastLower: NullableNumber[];
  forecastRange: NullableNumber[];
  forecastBand: Array<[number, number, number]>;
  priceMin: number;
  priceMax: number;
  historyLength: number;
};

function standardDeviation(values: number[]) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length);
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

function buildForecast(rows: BackendKlineRow[]): ForecastScenario {
  if (rows.length < 20) return { points: [] };
  const sample = rows.slice(-20);
  const closes = sample.map((row) => row[2]);
  const meanX = (closes.length - 1) / 2;
  const meanY = closes.reduce((sum, close) => sum + close, 0) / closes.length;
  const denominator = closes.reduce((sum, _, index) => sum + (index - meanX) ** 2, 0);
  const slope = closes.reduce((sum, close, index) => sum + (index - meanX) * (close - meanY), 0) / denominator;
  const lastClose = rows.at(-1)![2];
  const slopeRate = lastClose ? slope / lastClose : 0;
  const returns = closes.slice(1).map((close, index) => close / closes[index] - 1);
  const dailyVolatility = Math.min(0.15, Math.max(0.005, standardDeviation(returns)));
  const range = rows.slice(-60);
  const low60 = Math.min(...range.map((row) => row[3]));
  const high60 = Math.max(...range.map((row) => row[4]));
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
    const value = lastClose * (1 + slopeRate) ** (index + 1);
    const width = value * dailyVolatility * Math.sqrt(index + 1);
    return { date, value, lower: Math.max(value * 0.01, value - width), upper: value + width };
  });
  return { points, support, resistance };
}

function bollinger(rows: BackendKlineRow[]) {
  const upper: NullableNumber[] = [];
  const middle: NullableNumber[] = [];
  const lower: NullableNumber[] = [];
  rows.forEach((_, index) => {
    if (index < 19) {
      upper.push(null); middle.push(null); lower.push(null);
      return;
    }
    const closes = rows.slice(index - 19, index + 1).map((row) => row[2]);
    const mean = closes.reduce((sum, close) => sum + close, 0) / closes.length;
    const deviation = standardDeviation(closes);
    upper.push(mean + deviation * 2);
    middle.push(mean);
    lower.push(mean - deviation * 2);
  });
  return { upper, middle, lower };
}

export function buildKlineModel(rows: BackendKlineRow[], showForecast: boolean): KlineModel {
  if (!rows.length) return {
    dates: [], candles: [], turnover: [], forecast: [], bollingerUpper: [], bollingerMiddle: [], bollingerLower: [],
    forecastLine: [], forecastLower: [], forecastRange: [], forecastBand: [], priceMin: 0, priceMax: 1, historyLength: 0,
  };
  const scenario = showForecast ? buildForecast(rows) : { points: [] };
  const forecast = scenario.points;
  const dates = [...rows.map(([date]) => date), ...forecast.map(({ date }) => date)];
  const spacer = Array<NullableNumber>(Math.max(rows.length - 1, 0)).fill(null);
  const bands = bollinger(rows);
  const futureBlanks = Array<NullableNumber>(forecast.length).fill(null);
  const priceValues = [
    ...rows.flatMap((row) => [row[3], row[4]]),
    ...bands.lower.filter((value): value is number => value != null),
    ...bands.upper.filter((value): value is number => value != null),
    ...forecast.flatMap(({ lower, upper }) => [lower, upper]),
    ...(scenario.support == null ? [] : [scenario.support]),
    ...(scenario.resistance == null ? [] : [scenario.resistance]),
  ];
  const rawMin = Math.min(...priceValues);
  const rawMax = Math.max(...priceValues);
  const padding = Math.max((rawMax - rawMin) * 0.04, rawMax * 0.005);
  return {
    dates,
    candles: [...rows.map(([, open, close, low, high]) => [open, close, low, high]), ...forecast.map(() => "-")],
    turnover: [
      ...rows.map(([, open, close, , , volume]) => ({
        value: close * volume,
        itemStyle: { color: close >= open ? "#ef4444" : "#10b981" },
      })),
      ...forecast.map(() => ({ value: null })),
    ],
    forecast,
    support: scenario.support,
    resistance: scenario.resistance,
    bollingerUpper: [...bands.upper, ...futureBlanks],
    bollingerMiddle: [...bands.middle, ...futureBlanks],
    bollingerLower: [...bands.lower, ...futureBlanks],
    forecastLine: forecast.length ? [...spacer, rows.at(-1)![2], ...forecast.map(({ value }) => value)] : [],
    forecastLower: forecast.length ? [...spacer, rows.at(-1)![2], ...forecast.map(({ lower }) => lower)] : [],
    forecastRange: forecast.length ? [...spacer, 0, ...forecast.map(({ lower, upper }) => upper - lower)] : [],
    forecastBand: forecast.length ? [[rows.length - 1, rows.at(-1)![2], rows.at(-1)![2]], ...forecast.map(({ lower, upper }, index) => [rows.length + index, lower, upper] as [number, number, number])] : [],
    priceMin: rawMin - padding,
    priceMax: rawMax + padding,
    historyLength: rows.length,
  };
}

export function buildKlineSeries(model: KlineModel) {
  const series: Array<Record<string, unknown>> = [
    {
      name: "历史行情", type: "candlestick", data: model.candles, z: 4,
      itemStyle: { color: "#ef4444", color0: "#10b981", borderColor: "#ef4444", borderColor0: "#10b981" },
      markLine: model.forecast.length ? {
        symbol: "none", silent: true,
        data: [
          { name: "支撑", yAxis: model.support, lineStyle: { type: "dashed", color: "rgba(16,185,129,.75)", opacity: 0.75 } },
          { name: "压力", yAxis: model.resistance, lineStyle: { type: "dashed", color: "rgba(239,68,68,.9)", opacity: 0.9 } },
        ],
      } : undefined,
    },
    { name: "布林上轨", type: "line", data: model.bollingerUpper, showSymbol: false, connectNulls: false, clip: false, z: 3, lineStyle: { width: 1.2, type: "dashed", color: "rgba(59,130,246,.75)" } },
    { name: "布林中轨", type: "line", data: model.bollingerMiddle, showSymbol: false, connectNulls: false, clip: false, z: 3, lineStyle: { width: 1.2, color: "rgba(37,99,235,.7)" } },
    { name: "布林下轨", type: "line", data: model.bollingerLower, showSymbol: false, connectNulls: false, clip: false, z: 3, lineStyle: { width: 1.2, type: "dashed", color: "rgba(59,130,246,.75)" } },
    { name: "成交额（亿）", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: model.turnover, barMaxWidth: 12, z: 2 },
  ];
  if (model.forecast.length) {
    series.push(
      {
        name: "预测区间", type: "custom", data: model.forecastBand, clip: false, z: 2, silent: true,
        renderItem: (params: { dataIndex: number }, api: { value: (dimension: number) => number; coord: (value: number[]) => number[]; style: (style: Record<string, unknown>) => Record<string, unknown> }) => {
          if (params.dataIndex >= model.forecastBand.length - 1) return null;
          const current = [api.value(0), api.value(1), api.value(2)];
          const next = model.forecastBand[params.dataIndex + 1];
          const upperLeft = api.coord([current[0], current[2]]);
          const upperRight = api.coord([next[0], next[2]]);
          const lowerRight = api.coord([next[0], next[1]]);
          const lowerLeft = api.coord([current[0], current[1]]);
          return { type: "polygon", shape: { points: [upperLeft, upperRight, lowerRight, lowerLeft] }, style: api.style({ fill: "rgba(139,92,246,.14)", stroke: "rgba(139,92,246,.45)", lineWidth: 1 }) };
        },
      },
      { name: "技术情景预测", type: "line", data: model.forecastLine, showSymbol: false, connectNulls: false, clip: false, z: 7, lineStyle: { width: 2.5, color: "rgba(124,58,237,.8)" } },
    );
  }
  return series;
}
