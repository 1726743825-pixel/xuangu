# 外部资产与自定义策略目录规范

此目录用于保存用户提供的选股资产，不作为 FastAPI 路由或调度器的直接执行目录。

`source/` 中保留了现有 Node.js 资产：`stock_screener_latest.js`、`stock_screener.js`、`stock_screener_for_gist.js`、`a_stock_data_source.js` 及其 JSON 配置。真实密钥只可通过项目根目录 `.env` 配置。

## 目录约定

| 路径 | 用途 | 执行规则 |
| --- | --- | --- |
| `selection_script.py` | 可选的 Python 自定义策略 | 仅由 `app.strategy.engine` 动态加载 |
| `source/` | 原始 Node.js 脚本、配置和资料 | 只读保留；必须先经受控包装器转换输出 |
| `README.md` | 本目录的接入契约 | 与 `../docs/api-contract.md` 保持一致 |

`selection_script.py` 是供国内网络本机运行的适配器：它依次执行 `D:\Program Files\xuangu\zhuizhang\stock_screener.js`（strategy_name=`追涨`）和 `D:\Program Files\xuangu\chaodie\chaodie_screener.js`（strategy_name=`超跌`），然后解析各自新生成的 HTML 报告，每套策略最多返回前 10 只，作为 `/api/selections/import` 的 `items`。它不连接 Railway 数据库、不拉取项目行情，也不重算 MA/MACD/KDJ 或任何内部策略评分；评分、评级和明细完全以 D 盘正式脚本为准。超跌报告原始 130 分制会归一化到导入 API 的 0–100 分，并在 `indicators.raw_score/raw_score_max` 保留原始分。D 盘资产只读。生产端 `builtin.enabled=false` 且 custom 动态加载关闭，防止 Railway 回退执行内部策略。

本地每日自动化由仓库 `scripts/` 中的 PowerShell 任务安装脚本维护：消息面刷新任务优先使用 PowerShell 7（`pwsh.exe`）、隐藏窗口、UTF-8 日志；公司大模型只做快讯/标签预筛，DeepSeek 负责每日定稿、3 天复核和 Qwen3 覆盖不足时兜底。相关缓存位于 `D:\Program Files\xuangu\policy_scores*.json`、`D:\Program Files\xuangu\zixun_gongsidamoxing\` 与 `D:\Program Files\xuangu\Temp\Industry Classification_Tag\`。`TAG_REVIEW_BATCH_SIZE=10` 只表示标签规则复核的安全分批，不是快讯数量上限。

在 `backend/` 目录执行：

```powershell
python existing/selection_script.py > selections.json
```

输出为 JSON 数组；用它作为导入接口请求体的 `items`。脚本需要 Windows 本机安装 Node.js，并且 D 盘两套正式脚本与各自 `result/` 目录可访问；结果日期以官方 HTML 的生成日期为准。外层 `import_local_selections.py` 负责读取令牌并按策略分别上传。本机不需要 Railway 数据库或项目行情源配置。不要将密钥、数据库文件、临时下载行情或 `node_modules` 提交到此目录。

指定历史官方报告（不会运行 Node.js；指定日期必须与报告日期严格一致）：

```powershell
python existing/selection_script.py 2026-08-09 --report-path 'D:\Program Files\xuangu\zhuizhang\result\选股结果2026年08月09日.html'
# 或解析超跌报告
python existing/selection_script.py 2026-08-11 --report-path 'D:\Program Files\xuangu\chaodie\result\超跌反弹2026年08月11日.html'
```

导入器可通过一次性环境变量进入该只读模式；不要把路径写入 `.env`，以免日常任务重复导入历史报告：

```powershell
$env:XUANGU_OFFICIAL_REPORT_PATH = 'D:\Program Files\xuangu\zhuizhang\result\选股结果2026年08月09日.html'
python existing/import_local_selections.py --trade-date 2026-08-09 --env-file ..\.env --replace-existing
Remove-Item Env:XUANGU_OFFICIAL_REPORT_PATH
```

未指定报告的日常 15:05 模式在周末会拒绝执行 D 盘脚本。

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
