# 外部资产与自定义策略目录规范

此目录用于保存用户提供的选股资产，不作为 FastAPI 路由或调度器的直接执行目录。

`source/` 中保留了现有 Node.js 资产：`stock_screener_latest.js`、`stock_screener.js`、`stock_screener_for_gist.js`、`a_stock_data_source.js` 及其 JSON 配置。真实密钥只可通过项目根目录 `.env` 配置。

## 目录约定

| 路径 | 用途 | 执行规则 |
| --- | --- | --- |
| `selection_script.py` | 可选的 Python 自定义策略 | 仅由 `app.strategy.engine` 动态加载 |
| `source/` | 原始 Node.js 脚本、配置和资料 | 只读保留；必须先经受控包装器转换输出 |
| `README.md` | 本目录的接入契约 | 与 `../docs/api-contract.md` 保持一致 |

`selection_script.py` 是供国内网络本机运行的选股入口：它通过项目的数据层拉取日线，并复用内置策略评分，返回可直接作为 `/api/selections/import` 的 `items` 的记录。它不连接 Railway 数据库，也不执行 HTTP 导入；外层本地定时脚本负责上传。数据源不可用时它会抛出带原因的 `LocalSelectionDataError`，不会把失败伪装成空选股结果。生产端策略配置已关闭 custom 动态加载，防止 Railway 执行这个本地入口。

在 `backend/` 目录执行：

```powershell
python existing/selection_script.py 2026-08-07 > selections.json
```

输出为 JSON 数组；用它作为导入接口请求体的 `items`。本机需要安装 `backend/requirements.txt`，不需要 Railway 数据库、`JOB_API_TOKEN` 或 Tushare token；默认使用项目数据层配置的免费 K 线源。不要将密钥、数据库文件、临时下载行情或 `node_modules` 提交到此目录。

## Python 脚本接口

```python
def run_selection(trade_date: str) -> list[dict]:
    return [
        {
            "code": "600519",            # 或 stock_code；六位字符串
            "name": "贵州茅台",            # 或 stock_name
            "trade_date": trade_date,
            "strategy_name": "自定义策略",
            "score": 88.0,
            "price": 1512.3,
            "change_pct": 1.86,
            "reasons": ["站上20日均线"],
            "indicators": {"ma20": 1474.5}
        }
    ]
```

策略引擎负责把展示字段封装成数据库的 `signals` JSON：`price`、`change_pct`、`reasons` 和 `indicators`。脚本本身不得创建表、提交数据库事务、调用项目 HTTP 接口或启动后台任务。异常应抛出并由任务层记录到 `job_runs.error`，不要吞掉后返回伪成功结果。

`app.integrations.selection_adapter` 是旧演示兼容层；新代码不得从它导入或通过它执行脚本。
