import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import "./verify-kline-option.mjs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const dashboard = read("components/dashboard/Dashboard.tsx");
const table = read("components/dashboard/StockTable.tsx");
const api = read("components/dashboard/api.ts");
const detail = read("app/stock/[code]/page.tsx");
const page = read("app/page.tsx");

assert.match(api, /timeZone: "Asia\/Shanghai"/);
assert.match(page, /<Suspense><Dashboard \/><\/Suspense>/);
assert.match(dashboard, /useSearchParams/);
assert.match(dashboard, /useState\(\(\) => \(/);
assert.doesNotMatch(dashboard, /apiUrl\("\/api\/market\/indices"\)|MarketIndexCards|MarketIndices|indices\./);
assert.match(dashboard, /\.sort\(compareScoreDescending\)/);
assert.doesNotMatch(dashboard, /sortKey|sortDirection|onSort|StatsCards/);
assert.doesNotMatch(dashboard, /策略信号/);
assert.match(dashboard, /数据来源：AKShare（开源免费接口）｜本系统仅展示公开市场数据与技术指标，不构成任何投资建议。股市有风险，投资需谨慎/);

for (const name of ["上证指数", "深证成指", "创业板指", "科创50"]) assert.doesNotMatch(dashboard, new RegExp(name));
assert.match(table, /选入当日价格/);
assert.doesNotMatch(table, /当前价格|item\.current_price/);
assert.match(table, /总分/);
assert.match(table, /item\.selection_price/);
assert.match(table, /strategyBadgeClass/);
assert.match(table, /item\.strategy_name/);
assert.doesNotMatch(table, /formatPrice\(item\.price\)|策略信号|item\.selection_price_date|item\.current_price_as_of/);
assert.match(table, /table-fixed/);
assert.match(table, /<colgroup>/);
assert.match(detail, /href=\{backHref\}/);

assert.match(detail, /\[\{ value: "30m", label: "30分钟" \}, \{ value: "daily", label: "日K" \}, \{ value: "weekly", label: "周K" \}\]/);
assert.match(detail, /useState<Period>\("daily"\)/);
assert.match(detail, /row\.length !== 6/);
assert.match(detail, /typeof item === "number" && Number\.isFinite\(item\)/);
assert.doesNotMatch(detail, /\.map\(Number\)/);

console.log("dashboard contract checks passed");
