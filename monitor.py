# -*- coding: utf-8 -*-
"""
行情监控联动脚本
监控 ETH/USDT 现货价，达到目标价后自动市价平掉指定期权持仓（止盈）。
"""
import os
import sys
import time

os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7899")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7899")

from binance_mcp.config import ConfigManager
from binance_mcp.tools import BinanceMCPTools

# ============ 配置 ============
ACCOUNT = "main"
MONITOR_SYMBOL = "ETH/USDT"                 # 监控的现货交易对
TARGET_PRICE = 2525.0                       # 触发价格（ETH 达到或超过此价即触发）
OPTION_CCXT_SYMBOL = "ETH/USDT:USDT-260911-2600-C"  # 要平仓的期权（ccxt格式）
POLL_SECONDS = 5                            # 轮询间隔（秒）
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.log")
# ================================

tools = BinanceMCPTools(ConfigManager())


def log(msg):
    line = "[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_eth_price():
    t = tools.get_ticker(MONITOR_SYMBOL)
    return float(t.get("last"))


def get_position():
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    positions = ex.fetch_option_positions(None) or []
    for p in positions:
        if p.get("symbol") == OPTION_CCXT_SYMBOL:
            return p
    return None


def close_market(pos):
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    info = pos.get("info") or {}
    bsym = info.get("symbol")
    pos_side = (pos.get("side") or "long").lower()
    close_side = "SELL" if pos_side == "long" else "BUY"
    qty = pos.get("contracts") or 0
    params = {
        "symbol": bsym,
        "side": close_side,
        "type": "MARKET",
        "quantity": str(qty),
        "reduceOnly": True,
    }
    return ex.eapiPrivatePostOrder(params)


def main():
    log("=" * 50)
    log("启动监控：{} 达到 {} 时，市价平仓 {}".format(MONITOR_SYMBOL, TARGET_PRICE, OPTION_CCXT_SYMBOL))
    triggered = False
    while True:
        try:
            px = get_eth_price()
            log("ETH 当前价 {:.2f}".format(px))
            if px >= TARGET_PRICE:
                triggered = True
                log(">>> 触发！ETH {:.2f} >= {:.2f}，准备平仓".format(px, TARGET_PRICE))
                pos = get_position()
                if not pos:
                    log(">>> 未找到期权持仓 {}，无法平仓（可能已平仓）".format(OPTION_CCXT_SYMBOL))
                else:
                    r = close_market(pos)
                    log(">>> 市价平仓结果: {}".format(r))
                break
        except Exception as e:
            log("错误: {}".format(e))
        time.sleep(POLL_SECONDS)
    log("监控结束（触发={}）".format(triggered))


if __name__ == "__main__":
    main()
