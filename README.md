# 选股每日选股台

一个适合本机运行的 A 股每日选股台：FastAPI 后端 + SQLite + Next.js 前端。

## 快速启动

### 1. 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

打开 http://localhost:3000 。后端 API 文档位于 http://localhost:8000/docs。

## 已放入的现有脚本

你提供的 Node.js 选股脚本和配置已复制到 `backend/existing/source/`，包括行情数据源、三个选股脚本、策略规格和政策评分文件。原目录 `D:\Program Files\xuangu` 未被修改。

这些脚本当前作为原始资产保存，网站仍使用适配器运行，避免启动网站时自动触发外部行情请求。下一步接入时优先使用 `stock_screener_latest.js`，再将其输出转换为网站的统一结果格式。

## 接入你的现有脚本

如果希望直接接入 Python 版本，可将选股脚本命名为 `selection_script.py` 放到 `backend/existing/`，并提供：

```python
def run_selection(trade_date: str | None = None) -> list[dict]:
    return [
        {
            "code": "600519",
            "name": "贵州茅台",
            "trade_date": trade_date,
            "price": 1500.0,
            "change_pct": 1.2,
            "score": 88,
            "strategy_name": "你的策略",
            "reasons": ["站上20日均线"],
            "indicators": {"ma20": 1480, "rsi": 62},
        }
    ]
```

现在没有放入外部脚本时，系统会使用内置演示数据，保证页面可以先运行和体验。

## 环境变量

复制 `.env.example` 为 `.env`，按需配置数据源和前端 API 地址。真实 API key 不要提交到 Git。

## 测试

```powershell
cd backend
pytest
```

## Docker

```powershell
docker compose up --build
```

## 功能分支

项目预留了 `feature/product-ui`、`feature/market-data`、`feature/strategy-engine`、`feature/backend-api`、`feature/database`、`feature/scheduler`、`feature/frontend-dashboard`、`feature/testing-deployment` 分支；当前可运行版本合并在 `main`。
