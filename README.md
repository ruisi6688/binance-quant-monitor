# 币安监控量化

基于 **binance-mcp + Binance API** 的本地量化交易监控系统，包含：

## 功能模块

| 文件 | 功能 |
|------|------|
| `app.py` | Web 交易面板后端（Flask），行情/K线/账户/持仓/下单 REST API |
| `static/index.html` | 交易面板前端（现货/合约/期权，含期权链与止盈止损设置） |
| `btc_opt_monitor.py` | 期权持仓实时监控（WebSocket/轮询双源、到价市价平仓、断流反复报警） |
| `alert.py` | 价格提醒（到价推送钉钉） |
| `strategy.py` | 条件开仓策略（BTC 触发价 → 自动买入期权，含止盈止损状态机） |
| `activity_watcher.py` | 账户活动监控（持仓/挂单变化推送钉钉，覆盖手机端操作） |
| `monitor.py` | ETH 价格触发平仓监控（示例） |
| `opt_stop_monitor.py` | 期权价格止损监控（示例） |
| `notify.py` | 钉钉机器人通知模块 |

## 依赖

- Python 3.10+
- [binance-mcp](https://github.com/shanrichard/binance-mcp)（`pip install` 本地安装，含 ccxt）
- Flask 3.x
- 网络：需要代理访问 Binance（中国大陆环境）

## 配置

1. **代理**：所有脚本默认走 `http://127.0.0.1:7899`（FlClash/ZY），可用环境变量覆盖
2. **币安密钥**：存放在 binance-mcp 配置 `~/.config/binance-mcp/config.json`（Fernet 加密），账户 ID 默认 `main`
3. **钉钉通知**：将 `notify.py` 与 `btc_opt_monitor.py` 中的 `YOUR_DINGTALK_WEBHOOK_TOKEN` 替换为你的钉钉机器人 Webhook Token（安全设置需含关键词"监控"）

## 使用

```bash
# 启动 Web 面板
python app.py        # http://127.0.0.1:8900

# 期权持仓监控（改文件顶部配置：合约/触发价/方向）
python btc_opt_monitor.py

# 价格提醒
python alert.py
```

## 说明

- 币安期权不支持交易所原生条件单（仅 LIMIT/MARKET），止盈止损依赖本地监控，**电脑与代理需保持运行**
- 所有触发动作都会推送钉钉通知（下单/平仓/断流报警）
- 监控带断流看门狗：数据中断 >2 秒立即报警并每 8 秒重复，直至恢复

## 免责声明

本仓库仅供个人学习与自动化研究，不构成投资建议。加密货币交易有极高风险，盈亏自负。
