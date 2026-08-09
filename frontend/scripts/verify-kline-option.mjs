import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../components/charts/klineModel.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleRecord = { exports: {} };
const sandbox = { module: moduleRecord, exports: moduleRecord.exports };
vm.runInNewContext(compiled, sandbox, { filename: "klineModel.js" });
const { buildKlineModel, buildKlineSeries } = moduleRecord.exports;

const rows = Array.from({ length: 30 }, (_, index) => {
  const close = 100 + index * 0.45 + Math.sin(index / 2) * 2.4;
  const open = close - Math.cos(index) * 0.8;
  return [`2026-07-${String(index + 1).padStart(2, "0")}`, open, close, Math.min(open, close) - 1.2, Math.max(open, close) + 1.3, 1_000_000 + index * 25_000];
});
const model = buildKlineModel(rows, true);
const series = buildKlineSeries(model);
const names = new Set(series.map((item) => item.name));

for (const name of ["布林上轨", "布林中轨", "布林下轨", "技术情景预测", "预测区间"]) assert.ok(names.has(name), `${name} series missing`);
const history = series.find((item) => item.name === "历史行情");
assert.deepEqual(Array.from(history.markLine.data, (item) => item.name), ["支撑", "压力"]);
assert.equal(model.forecast.length, 5);
assert.equal(model.dates.length, rows.length + 5);
assert.deepEqual(Array.from(model.dates.slice(rows.length)), Array.from(model.forecast, (item) => item.date));
assert.ok(model.forecastLine.slice(0, rows.length - 1).every((value) => value == null));
assert.equal(model.forecastLine[rows.length - 1], rows.at(-1)[2]);
assert.ok(model.bollingerUpper.filter((value) => value != null).length >= 11);
assert.ok(model.bollingerMiddle.filter((value) => value != null).length >= 11);
assert.ok(model.bollingerLower.filter((value) => value != null).length >= 11);

const upperBound = Math.max(...model.bollingerUpper.filter(Number.isFinite), ...model.forecast.map((item) => item.upper), model.resistance);
const lowerBound = Math.min(...model.bollingerLower.filter(Number.isFinite), ...model.forecast.map((item) => item.lower), model.support);
assert.ok(model.priceMax > upperBound, "price axis must cover Bollinger/forecast/resistance upper bounds");
assert.ok(model.priceMin < lowerBound, "price axis must cover Bollinger/forecast/support lower bounds");
for (const name of ["布林上轨", "布林中轨", "布林下轨", "技术情景预测", "预测区间"]) {
  assert.equal(series.find((item) => item.name === name).clip, false, `${name} must not be clipped`);
}

console.log("K-line option regression checks passed");
