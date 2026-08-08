# 现有资产放置位置

你提供的 Node.js 源文件已经放在 `source/` 子目录中，包含 `stock_screener_latest.js`、`stock_screener.js`、`stock_screener_for_gist.js`、`a_stock_data_source.js` 以及 JSON 配置文件。

当前网站适配器优先寻找 `backend/existing/selection_script.py`。如果要接入现有 Node.js 选股脚本，需要增加一个 JSON 输出包装器，将脚本结果转换为：`code/name/trade_date/price/change_pct/score/strategy_name/reasons/indicators`。

行情和消息 skill 可以放在这里，或由 `app/integrations/market_adapter.py` 调用。真实密钥请通过项目根目录 `.env` 配置。
