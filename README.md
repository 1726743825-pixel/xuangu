# 选股每日选股台

适合本机运行的 A 股每日选股台：FastAPI 后端、SQLite 和 Next.js 前端。

## 快速启动

```powershell
# 后端
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

打开 http://localhost:3000；后端 OpenAPI 文档位于 http://localhost:8000/docs。

## 架构与分支协作

所有分支必须以 [API 契约](backend/docs/api-contract.md) 为接口唯一事实来源；不要以页面实现、演示数据或旧适配器反推接口。

| 分支 | 职责 | 上游依赖 | 合并前必须确认 |
| --- | --- | --- | --- |
| `feature/database` | SQLAlchemy 模型、Alembic 迁移、DAO | 无 | 表、约束、索引和迁移可升级 |
| `feature/market-data` | 股票主数据、交易日、日线采集与入库 | database | 写入 `stocks`、`trade_calendar`、`daily_quotes` |
| `feature/strategy-engine` | 指标、策略执行、回测、自定义脚本适配 | database、market-data | 只通过 DAO 读写；输出选股契约 |
| `feature/backend-api` | FastAPI 路由与响应序列化 | strategy-engine | 与 API 契约逐字段一致 |
| `feature/frontend-dashboard` | 数据看板和详情页数据接入 | backend-api | 严格按 API 契约消费 |
| `feature/product-ui` | 视觉、交互与组件体系 | frontend-dashboard | 不改变接口字段语义 |
| `feature/scheduler` | 收盘后同步与选股调度、运行审计 | market-data、strategy-engine | 幂等、避免重入、写入 `job_runs` |
| `feature/testing-deployment` | 测试、镜像、部署与迁移验证 | 所有功能分支 | 全量测试、Alembic 升级和健康检查通过 |

合并顺序为：Phase 1 `database → market-data`；Phase 2 `strategy-engine → backend-api`；Phase 3 `frontend-dashboard → product-ui`；Phase 4 `scheduler + testing-deployment`。跨阶段合并前，必须先完成契约评审，尤其检查选股结果和 K 线字段、日期格式及空值约定。

## 数据库定稿（v1）

`backend/app/db/migrations/versions/20260808_0001_initial_schema.py` 是当前数据库结构的唯一迁移基线。共五张表：`stocks`、`trade_calendar`、`daily_quotes`、`selection_results`、`job_runs`。其中日线唯一键为 `(stock_code, trade_date)`，选股结果唯一键为 `(stock_code, trade_date, strategy_name)`；完整字段定义见 API 契约。后续结构变更只能新增 Alembic migration，禁止改写已合并迁移。

## K 线格式标准

面向 ECharts 的 K 线点固定为 `[date, open, close, low, high, vol]`，日期为 `YYYY-MM-DD`，价格和成交量均为数值。数据库内部保持具名的 `daily_quotes` 字段；由后端 API 在响应边界进行序列化，前端不得依赖数据库列顺序。完整响应示例和空值规则见 API 契约。

## 接入现有选股脚本

Python 自定义策略的唯一入口是 `backend/existing/selection_script.py`，由 `app.strategy.engine` 动态加载；当前文件尚未放入仓库。脚本必须只定义 `run_selection(trade_date: str) -> list[dict]`，并返回策略引擎契约中的字段。Node.js 源资产保留在 `backend/existing/source/`，不能由 Web 请求直接执行；如需使用，先由受控包装器转换为同一 Python/JSON 输出。

现有 Node.js 资产包括行情数据源、三个选股脚本、策略规格和政策评分文件；原始目录 `D:\Program Files\xuangu` 未被修改。

`backend/app/integrations/selection_adapter.py` 属于旧演示适配器，不是新策略引擎入口，后续分支不得将其重新接入任务调度。脚本返回的理由、价格和指标必须被封装进 `selection_results.signals` 的规范 JSON，避免 API 层丢失展示字段。

## Deployment

### 本地 Docker Compose

根目录 `Dockerfile` 是多阶段、多目标构建：前端使用 `node:20-alpine` 完成依赖安装和 Next.js standalone 构建，后端使用 `python:3.11-slim` 预构建 wheels 后生成运行镜像。`docker-compose.yml` 分别选择 `frontend` 和 `backend` 目标，并通过命名卷持久化 SQLite。

```powershell
Copy-Item .env.example .env
docker compose up --build
```

打开 http://localhost:3000；API 健康检查为 http://localhost:8000/api/health。停止服务使用 `docker compose down`；只有明确需要删除本地 SQLite 数据时才使用 `docker compose down --volumes`。

主要环境变量如下：

| 变量 | 用途 | 本地默认值 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | 浏览器访问的后端公网地址；构建前端时写入 | `http://localhost:8000` |
| `DATABASE_PATH` | SQLite 文件路径；相对路径按 `backend/` 解析 | `data/xuangu.db` |
| `DATABASE_URL` | 可选 SQLAlchemy URL，设置后优先于 `DATABASE_PATH` | 未设置 |
| `CORS_ORIGINS` | 允许的前端 Origin，逗号分隔 | 本地 3000 端口 |
| `ENABLE_SCHEDULER` | 是否启用 API 进程内调度器 | `true` |
| `QUOTE_SYNC_HOUR` / `QUOTE_SYNC_MINUTE` | Asia/Shanghai 时区的前复权日 K 同步时间 | `15` / `00` |
| `SELECTION_RUN_HOUR` / `SELECTION_RUN_MINUTE` | Asia/Shanghai 时区的进程内选股时间 | `15` / `30` |
| `JOB_API_TOKEN` | 保护云端选股触发接口；生产必须使用随机长字符串 | `change-me` |
| `TUSHARE_TOKEN` | 可选，启用 Tushare 历史行情 | 未设置 |
| `QUOTE_SOURCES` | 日 K 数据源优先级，逗号分隔；无令牌时自动跳过 Tushare | `tencent,baidu,sina,tushare` |
| `QUOTE_SOURCE_FAILURE_THRESHOLD` / `QUOTE_SOURCE_COOLDOWN` | 单源连续失败熔断阈值 / 冷却秒数 | `3` / `300` |
| `EASTMONEY_MIN_INTERVAL` | 东方财富请求最小间隔（秒） | `1.0` |

完整清单和示例值见 `.env.example`。`.env` 已被 Git 忽略，不要提交真实令牌。

### 行情同步

每日 `15:00`（Asia/Shanghai）先通过腾讯财经 HTTP 批量报价发现目标 A 股代码（`600/601/603/000/001/002/300/301`，排除 `688/8/4/43`），再按 `QUOTE_SOURCES` 从腾讯、百度股市通、新浪财经、可选 Tushare 依次获取前复权日 K，写入 `stocks` 与 `daily_quotes`；任一来源失败会自动尝试下一个来源，单只股票全部失败也不会中断整批。连续失败的来源会短暂熔断，避免海外环境反复等待已被屏蔽的站点。`15:30` 选股任务仅在当日行情存在时执行。首次同步会同时灌入近 160 根日 K，以满足策略所需的历史指标窗口。部署在海外时不使用 mootdx 的 TCP 7709。股票列表的远端降级顺序为可选 Tushare、东方财富；全部远端不可用时，系统按 `backend/config/strategy.json` 的 `allowed_prefixes` 启用内置小型股票池，记录错误但继续 K 线同步，避免选股链路因主数据为空而中断。

可通过带令牌的接口手动触发：

```text
POST /api/quotes/sync
X-Job-Token: <JOB_API_TOKEN>
Content-Type: application/json

{"date":"2026-08-07"}
```

不传 `date` 时使用最近一个工作日。接口异步返回 `202 Accepted`，同步过程中不会阻塞 Web 请求。

### 数据来源与许可

腾讯 HTTP 批量报价、腾讯/百度行情接口与多源优先级参考 [a-stock-data](https://github.com/simonlin1212/a-stock-data) 的公开实现（Apache-2.0）；新浪前复权换算参考 [AKShare 新浪行情实现](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_zh_a_sina.py)。本项目未打包这些项目代码或依赖，运行时继续复用现有 `httpx` 依赖。百度直接使用其前复权序列；新浪原始日 K 使用官方复权因子转换 OHLC；Tushare 按 `adj_factor / 最新 adj_factor` 转换，所有来源统一日期、价量与金额单位。

### CI 与每日选股

`.github/workflows/ci.yml` 在 push 和 pull request 时并行运行 Python 3.11 下的全量 Pytest，以及 Node.js 20/pnpm 下的 Next.js production build。API 测试包含健康检查、基础列表响应和定时任务鉴权。

`.github/workflows/daily-selection.yml` 每天在 `07:30 UTC`（北京时间 `15:30`）调用已部署后端，也支持手动指定交易日。非交易日由行情/策略层返回空结果。仓库中需配置：

- Actions variable `BACKEND_URL`：后端公网根地址，例如 `https://xuangu-api.onrender.com`。
- Actions secret `JOB_API_TOKEN`：必须与后端同名环境变量一致。

云端部署建议设置 `ENABLE_SCHEDULER=false`，由 GitHub Actions 单点触发，避免应用内调度器与云工作流重复执行。

### Render / Railway 后端

Render 可直接导入根目录 `render.yaml`。Blueprint 使用免费 Web Service、Dockerfile 最终 `backend` 阶段和 `/api/health` 健康检查。创建后设置 `CORS_ORIGINS` 为 Vercel 域名，并把 Render 生成的 `JOB_API_TOKEN` 同步到 GitHub Actions。Render 免费实例不提供持久磁盘，因此配置中的 `/tmp/xuangu.db` 会在重建或休眠恢复后丢失；免费方案适合演示，需长期保留结果时请选择持久磁盘或外部数据库。

Railway 会读取 `railway.toml` 和根目录 Dockerfile。服务变量至少设置：

```text
DATABASE_PATH=/app/data/xuangu.db
ENABLE_SCHEDULER=false
CORS_ORIGINS=https://your-frontend.vercel.app
JOB_API_TOKEN=<random-long-secret>
TUSHARE_TOKEN=<optional>
```

如需持久化 SQLite，在 Railway 控制台挂载 Volume 到 `/app/data`。部署成功后将生成的公网域名写入 GitHub `BACKEND_URL`。

### Vercel 前端

在 Vercel 导入仓库时将 **Root Directory** 设置为 `frontend`；`frontend/vercel.json` 会使用 Next.js 和锁定的 pnpm 依赖。部署前设置：

```text
NEXT_PUBLIC_API_BASE=https://your-backend.example.com
```

该变量会在 Next.js 构建时写入浏览器包；修改后必须重新部署。后端的 `CORS_ORIGINS` 应填入实际 Vercel Production 域名，多个域名用逗号分隔。

### 本地验证

```powershell
Set-Location backend
python -m pytest -q

Set-Location ../frontend
corepack pnpm install --frozen-lockfile
corepack pnpm build

Set-Location ..
docker compose config
docker build --target backend -t xuangu-backend .
docker build --target frontend -t xuangu-frontend .
```
