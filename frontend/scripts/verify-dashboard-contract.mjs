import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import "./verify-kline-option.mjs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const dashboard = read("components/dashboard/Dashboard.tsx");
const cards = read("components/dashboard/MarketIndexCards.tsx");
const table = read("components/dashboard/StockTable.tsx");
const api = read("components/dashboard/api.ts");
const detail = read("app/stock/[code]/page.tsx");

assert.match(api, /timeZone: "Asia\/Shanghai"/);
assert.match(dashboard, /useState\(getShanghaiToday\)/);
assert.match(dashboard, /apiUrl\("\/api\/market\/indices"\)/);
assert.match(dashboard, /\.sort\(compareScoreDescending\)/);
assert.doesNotMatch(dashboard, /sortKey|sortDirection|onSort|StatsCards/);
assert.doesNotMatch(dashboard, /策略信号/);
assert.match(dashboard, /数据来源：AKShare（开源免费接口）｜本系统仅展示公开市场数据与技术指标，不构成任何投资建议。股市有风险，投资需谨慎/);

for (const name of ["上证指数", "深证成指", "创业板指", "科创50"]) assert.match(cards, new RegExp(name));
assert.match(cards, /grid-cols-2 gap-3 lg:grid-cols-4/);
assert.match(table, /选入当日价格/);
assert.match(table, /当前价格/);
assert.match(table, /总分/);
assert.match(table, /item\.selection_price/);
assert.match(table, /item\.current_price/);
assert.doesNotMatch(table, /formatPrice\(item\.price\)|策略信号|>\{item\.strategy_name\}<|item\.selection_price_date|item\.current_price_as_of/);
assert.doesNotMatch(cards, /item\.as_of|observed_at|更新时间/);
assert.match(table, /table-fixed/);
assert.match(table, /<colgroup>/);

assert.match(detail, /\[\{ value: "30m", label: "30分钟" \}, \{ value: "daily", label: "日K" \}, \{ value: "weekly", label: "周K" \}\]/);
assert.match(detail, /useState<Period>\("daily"\)/);
assert.match(detail, /row\.length !== 6/);
assert.match(detail, /typeof item === "number" && Number\.isFinite\(item\)/);
assert.doesNotMatch(detail, /\.map\(Number\)/);

console.log("dashboard contract checks passed");
