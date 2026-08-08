# API 与数据契约（v1）

本文件是 `database`、`market-data`、`strategy-engine`、`backend-api` 与前端分支之间的唯一接口约定。字段名、日期、空值和数组顺序不得由任一分支单独改变。破坏性修改须新增版本化端点或经全体消费者确认后随 migration 一并合并。

## 数据库边界

| 表 | 主键 / 唯一键 | 关键字段 | 所有者 |
| --- | --- | --- | --- |
| `stocks` | `code` | `name`, `industry`, `list_date`, `is_st` | market-data |
| `trade_calendar` | `trade_date` | `is_open` | market-data |
| `daily_quotes` | `id`；`(stock_code, trade_date)` 唯一 | `open`, `high`, `low`, `close`, `volume`, `amount` | market-data |
| `selection_results` | `id`；`(stock_code, trade_date, strategy_name)` 唯一 | `signals` JSON, `score` | strategy-engine |
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
  "amount": 1860000000.0
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
| `/api/selections/run` | POST | 请求体 `{ "date": "YYYY-MM-DD" }`（可省略）；202，`data.status = "accepted"` |
| `/api/stock/{code}/detail` | GET | `data: StockDetail`；无股票为 404 |
| `/api/stock/{code}/kline?period=daily` | GET | `data: KlinePoint[]`，见下节 |

选股结果 API 对象固定为：

```json
{
  "code": "600519",
  "name": "贵州茅台",
  "trade_date": "2026-08-07",
  "price": 1512.3,
  "change_pct": 1.86,
  "score": 92.0,
  "strategy_name": "趋势强度",
  "industry": "白酒",
  "reasons": ["站上20日均线"],
  "indicators": {"ma20": 1474.5}
}
```

`price`、`change_pct`、`score`、`industry` 可以是 `null`；`reasons` 和 `indicators` 始终存在。

## K 线 API（ECharts）

`GET /api/stock/{code}/kline` 的 `data` 是按日期升序排列的二维数组。每一项严格为：

```json
["2026-08-07", 1500.0, 1512.3, 1490.0, 1520.0, 1234567]
```

数组索引的语义固定如下：`[date, open, close, low, high, vol]`。前端 ECharts 的类目轴取 `item[0]`，K 线数据取 `item.slice(1, 5)`，成交量取 `item[5]`。不得交换 high/low，也不得用 `MM-DD` 替换完整日期。某根日线的 OHLC 任一值缺失时，后端应过滤该点；`vol` 可为 `0`，不可为负数。

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
