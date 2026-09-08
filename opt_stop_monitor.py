# -*- coding: utf-8 -*-
"""
期权价格监控脚本（止损用）
监控期权标记价，跌到目标价后自动市价平仓（止损 / 保本）。
币安期权不支持原生条件单，需本地盯盘。
"""
import os
import time

os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7899")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7899")

from binance_mcp.config import ConfigManager
from binance_mcp.tools import BinanceMCPTools

# ============ 配置 ============
ACCOUNT = "main"
OPTION_BINANCE_SYMBOL = "ETH-260911-2600-C"          # 期权合约
STOP_PRICE = 17.0                                    # 触发价：期权价 <= 17 时平仓
POLL_SECONDS = 5
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "optstop.log")
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


def get_option_state():
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    m = ex.eapiPublicGetMark({"symbol": OPTION_BINANCE_SYMBOL})
    mark = float(m[0]["markPrice"]) if m else None
    pos = ex.eapiPrivateGetPosition()
    hold = 0.0
    for p in pos:
        if p.get("symbol") == OPTION_BINANCE_SYMBOL and (p.get("side") or "").upper() == "LONG":
            hold = float(p.get("quantity") or 0)
    return mark, hold


def close_market(qty):
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    return ex.eapiPrivatePostOrder({
        "symbol": OPTION_BINANCE_SYMBOL,
        "side": "SELL",
        "type": "MARKET",
        "quantity": str(qty),
        "reduceOnly": True,
    })


def main():
    log("=" * 50)
    log("启动期权止损监控：{} 价格 <= {} 时市价平仓".format(OPTION_BINANCE_SYMBOL, STOP_PRICE))
    while True:
        try:
            mark, hold = get_option_state()
            if hold <= 0:
                log("已无持仓，监控退出")
                break
            log("期权价 {:.2f}（持仓 {} 张，止损线 {}）".format(mark if mark else -1, hold, STOP_PRICE))
            if mark is not None and mark <= STOP_PRICE:
                log(">>> 触发！期权价 {:.2f} <= {:.2f}，市价平仓 {} 张".format(mark, STOP_PRICE, hold))
                r = close_market(hold)
                log(">>> 平仓结果: {}".format(r))
                break
        except Exception as e:
            log("错误: {}".format(e))
        time.sleep(POLL_SECONDS)
    log("监控结束")


if __name__ == "__main__":
    main()
