# -*- coding: utf-8 -*-
"""
价格提醒监控：监控交易对价格，到达设置的条件后推送钉钉通知。
可同时监控多个条件；触发后自动继续等待其他条件（不退出）。
"""
import os
import time

os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7899")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7899")

from binance_mcp.config import ConfigManager
from binance_mcp.tools import BinanceMCPTools
from notify import send_dingtalk

tools = BinanceMCPTools(ConfigManager())

# ============ 配置 ============
SYMBOL = "BTC/USDT"                 # 监控交易对
TARGETS = [                         # (价格, 触发方向: "above"=涨过 / "below"=跌破, 备注)
    (79000.0, "below", "BTC 跌破 79,000 —— 计划入场 ETH 看涨期权"),
]
POLL_SECONDS = 10
# ================================

fired = {i: False for i in range(len(TARGETS))}


def log(msg):
    print("[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def main():
    log("价格提醒启动: {} 条件 {} 个".format(SYMBOL, len(TARGETS)))
    send_dingtalk("📡 价格提醒已启动", "监控 {}，目标：{}".format(
        SYMBOL, "；".join("{} {}".format("高于" if d == "above" else "低于", p) for p, d, _ in TARGETS)))
    while True:
        try:
            t = tools.get_ticker(SYMBOL)
            px = float(t.get("last"))
            for i, (target, direction, note) in enumerate(TARGETS):
                if fired[i]:
                    continue
                if (direction == "above" and px >= target) or (direction == "below" and px <= target):
                    fired[i] = True
                    msg = "🔔 {} 当前价 **{:.0f}**\n\n{}".format(SYMBOL, px, note)
                    log("触发: {}".format(msg))
                    send_dingtalk("🚨 价格提醒", msg)
        except Exception as e:
            log("错误: {}".format(e))
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
