# API 与数据契约（v1）

本文件是 `database`、`market-data`、`strategy-engine`、`backend-api` 与前端分支之间的唯一接口约定。字段名、日期、空值和数组顺序不得由任一分支单独改变。破坏性修改须新增版本化端点或经全体消费者确认后随 migration 一并合并。

## 数据库边界

| 表 | 主键 / 唯一键 | 关键字段 | 所有者 |
| --- | --- | --- | --- |
| `stocks` | `code` | `name`, `industry`, `list_date`, `is_st` | market-data |
| `trade_calendar` | `trade_date` | `is_open` | market-data |
| `daily_quotes` | `id`；`(stock_code, trade_date)` 唯一 | `open`, `high`, `low`, `close`, `volume`, `amount`, `source` | market-data |
| `intraday_quotes` | `id`；`(stock_code, interval, trade_datetime)` 唯一 | `open`, `high`, `low`, `close`, `volume`, `amount`, `amount_estimated`, `source` | market-data |
| `selection_results` | `id`；`(stock_code, trade_date, strategy_name)` 唯一 | `signals` JSON, `score`, `selection_price`, `selection_price_date` | strategy-engine |
| `stock_quote_snapshots` | `stock_code` | `price`, `change_pct`, `as_of`, `source` | market-data |
| `market_snapshots` | `code` | `name`, `level`, `change_pct`, `as_of`, `source` | market-data |
| `job_runs` | `id` | `status`, `trade_date`, `started_at`, `finished_at`, `result_count`, `error` | scheduler |

所有业务表均有 `created_at`、`updated_at`。`daily_quotes.stock_code` 和 `selection_results.stock_code` 外键引用 `stocks.code`，删除股票级联删除其日线和选股记录。日期存为 SQLite `DATE`，API 一律输出 `YYYY-MM-DD`；时间输出 ISO 8601 字符串。

### 日线入库记录

```json
{
  "stock_code": "600519",
  "trade_date": "2026-08-07",
  "open": 1500.0,
  "high": 1520.0,
  "low": 1490.0,
  "close": 1512.3,
  "volume": 1234567,
  "amount": 1860000000.0,
  "source": "akshare-eastmoney"
}
```

同一股票同一交易日必须 upsert，不得插入重复记录。价格字段精度为四位小数，成交量/成交额精度为四位小数；停牌或上游缺失可存 `null`，但不得以字符串 `"--"` 入库。

### 选股结果与 `signals`

策略引擎保存前必须产生下列规范形状；API 展示字段全部从此形状读取：

```json
{
  "stock_code": "600519",
  "stock_name": "贵州茅台",
  "industry": "白酒",
  "trade_date": "2026-08-07",
  "strategy_name": "趋势强度",
  "score": 92.0,
  "signals": {
    "price": 1512.3,
    "change_pct": 1.86,
    "reasons": ["站上20日均线"],
    "indicators": {"ma5": 1498.2, "ma20": 1474.5, "rsi": 63.2}
  }
}
```

`score` 取 `0–100` 的数值。`signals.reasons` 必须为字符串数组，`signals.indicators` 必须为对象；缺失时分别写 `[]`、`{}`，不写 JSON 字符串。

`POST /api/selections/import` 复用 `JOB_API_TOKEN` / `X-Job-Token` 鉴权。请求体包含 `trade_date` 和 `items`；每个 item 必须写入 `strategy_name`。当前本地官方脚本只允许两类策略名：`追涨` 与 `超跌`。追涨原始分为 100 分制，直接导入 0–100；超跌原始分为 130 分制，导入器必须先归一化到 0–100，并在 `signals.indicators.raw_score` 与 `signals.indicators.raw_score_max = 130` 保留原始分制。后端以 `(stock_code, trade_date, strategy_name)` 幂等覆盖，同一交易日不同策略不得互相覆盖。

## HTTP API

所有成功响应使用统一信封，股票代码为六位字符串（例如 `600519`）：

```json
{"code": 0, "data": {}, "message": ""}
```

错误响应也使用该信封，`data` 为 `null`，HTTP 状态码和 `code` 一致。

| 路由 | 方法 | 响应核心结构 |
| --- | --- | --- |
| `/api/health` | GET | `data: { "status": "ok", "service": "xuangu-api" }` |
| `/api/stocks?page=1&size=20&industry=` | GET | `data: { "items", "page", "size", "total" }` |
| `/api/selections?date=YYYY-MM-DD&strategy=` | GET | `data: { "date", "strategy", "items", "count" }` |
| `/api/selections/import` | POST | 导入本地官方脚本选股结果；需 `X-Job-Token` |
| `/api/market/indices` | GET | `data: { "items": [{ "name", "code", "price", "change_pct", "as_of" }] }` |
| `/api/selections/run` | POST | 请求体 `{ "date": "YYYY-MM-DD" }`（可省略）；202，`data.status = "accepted"` |
| `/api/market/snapshots/import` | POST | 导入四指数和入选股票 AKShare 快照；需 `X-Job-Token` |
| `/api/quotes/import` | POST | 导入真实日 K；需 `X-Job-Token` |
| `/api/quotes/intraday/import` | POST | 导入真实 30 分钟 K；需 `X-Job-Token` |
| `/api/stock/{code}/detail` | GET | `data: StockDetail`；无股票为 404 |
| `/api/stock/{code}/kline?period=daily\|weekly\|30m` | GET | `data: KlinePoint[]`，见下节 |

选股结果 API 对象固定为：

```json
{
  "code": "600519",
  "name": "贵州茅台",
  "trade_date": "2026-08-07",
  "price": 1512.3,
  "selection_price": 1512.3,
  "selection_price_date": "2026-08-07",
  "current_price": 1520.8,
  "current_price_as_of": "2026-08-09T15:00:00+08:00",
  "change_pct": 1.86,
  "score": 92.0,
  "strategy_name": "趋势强度",
  "industry": "白酒",
  "reasons": ["站上20日均线"],
  "indicators": {"ma20": 1474.5}
}
```

`price` 是兼容字段，始终与固定的 `selection_price` 相同。`selection_price` 和 `selection_price_date` 来自 `selection_results` 固定列，必须成对出现；非交易日报告允许 `selection_price_date` 早于 `trade_date`，但不得晚于报告日期。`current_price` 和 `current_price_as_of` 只来自 `stock_quote_snapshots`，没有快照时为 `null`，不得回退到 `stocks` 或入选价。`change_pct`、换手率、连板数等权威报告字段不得被行情快照覆盖。`score`、`industry` 可以是 `null`；`reasons` 和 `indicators` 始终存在。

## 市场快照 API

`GET /api/market/indices` 始终按上证指数 `000001.SH`、深证成指 `399001.SZ`、创业板指 `399006.SZ`、科创50 `000688.SH` 的固定顺序返回四项。某指数从未有有效快照时仍保留该项，`price`、`change_pct`、`as_of` 为 `null`。

`POST /api/market/snapshots/import` 的 `indices` 必须恰好包含上述四项各一次，每项必须显式提供 `available`：

- `available: true` 时，`price` 必须为有限正数，`change_pct` 必须为有限数，`as_of` 必须为 ISO 8601 时间。
- `available: false` 时，三字段允许为 `null`；该项不入库、不清除已有值。若已有快照，GET 继续返回最近已知值及其原 `as_of`。
- `source` 必须匹配 `akshare-*`。指数和股票快照均按主键幂等 upsert，较旧 `as_of` 不得覆盖较新快照。

请求体同时包含 `indices` 和 `stocks`；`stocks` 可为空。接口使用现有 `X-Job-Token` / `JOB_API_TOKEN` 鉴权。

## K 线 API（ECharts）

`GET /api/stock/{code}/kline` 的 `data` 是按时间升序排列的二维数组。日线/周线每一项严格为：

```json
["2026-08-07", 1500.0, 1512.3, 1490.0, 1520.0, 1234567]
```

30 分钟线使用相同字段顺序，首项为带 Asia/Shanghai 偏移量的 ISO 时间，例如：

```json
["2026-08-07T09:30:00+08:00", 10.1, 10.5, 10.0, 10.8, 123456]
```

数组索引的语义固定如下：`[date_or_datetime, open, close, low, high, vol]`。前端 ECharts 的类目轴取 `item[0]`，K 线数据取 `item.slice(1, 5)`，成交量取 `item[5]`。不得交换 high/low，也不得用 `MM-DD` 替换完整日期。

日 K 和 30 分钟 K 导入均严格执行 `low <= open/close <= high`、OHLC 为有限正数、成交量为有限非负数；违反契约（包括截图错位造成的 `high < close`）返回 422。输出前再次过滤数据库中的坏行，禁止修正、补零、实时回退或生成模拟数据。日 K 的 `amount` 可为 `null`；30 分钟 K 的 `amount` 可为 `null`，并须显式给出 `amount_estimated`。新 AKShare 上传应提供匹配 `akshare-*` 的 `source` 并持久化；为兼容旧客户端，source 可省略，但提供时必须合法。

## 自定义脚本接入

脚本位置：`backend/existing/selection_script.py`。唯一受支持的入口：

```python
def run_selection(trade_date: str) -> list[dict]:
    ...
```

脚本输入日期已经过格式校验；它不得自行建表、调用 Web API 路由、提交事务或启动调度器。返回记录至少包含 `code`（或 `stock_code`）和 `name`（或 `stock_name`），其余字段按上文选股结果映射。合并前，strategy-engine 必须将旧字段 `indicators`、`reasons`、`price`、`change_pct` 规范化为 `signals` JSON；不得依赖旧的 `app.integrations.selection_adapter`。

## 合并门禁

1. database migration 可在空 SQLite 数据库升级，并保留外键与唯一约束。
2. market-data 写出的日线可被 strategy-engine 以具名字段读取。
3. backend-api 的 K 线响应通过数组顺序断言；前端使用 `response.data` 和相同索引读取。
4. 自定义脚本结果经过一次保存和读取后，`reasons`、`indicators`、`price`、`change_pct` 不丢失。
5. 前端类型声明与本文件字段及统一信封逐项匹配，未声明的字段不得成为运行时依赖。
