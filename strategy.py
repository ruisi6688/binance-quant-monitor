# -*- coding: utf-8 -*-
"""
自动策略：BTC 跌破 79150 -> 90%仓位市价买 ETH-260911-2575-C
          ETH 跌破 2415 -> 市价平仓(止损)
          ETH 涨到 2510 -> 市价平仓(止盈)
状态持久化，重启后可恢复。
"""
import os
import sys
import json
import time

os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7899")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7899")

from binance_mcp.config import ConfigManager
from binance_mcp.tools import BinanceMCPTools
from notify import send_dingtalk

# ============ 配置 ============
ACCOUNT = "main"
BTC_TRIGGER = 79150.0       # BTC 触发价(<=)
OPTION_SYMBOL = "ETH/USDT:USDT-260911-2575-C"   # ccxt格式
OPTION_BINANCE = "ETH-260911-2575-C"
ETH_SL = 2415.0             # ETH 止损价(<=)
ETH_TP = 2510.0             # ETH 止盈价(>=)
POSITION_PCT = 0.9          # 买入用可用资金的90%
POLL_SECONDS = 10
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_state.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy.log")
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


def notify(title, msg):
    send_dingtalk(title, msg)
    log("钉钉推送: {} - {}".format(title, msg))


def get_price(symbol):
    t = tools.get_ticker(symbol)
    return float(t.get("last"))


def get_opt_available():
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    ma = ex.eapiPrivateGetMarginAccount()
    for a in ma.get("asset", []):
        if a.get("asset") == "USDT":
            return float(a.get("available") or 0)
    return 0.0


def get_position_qty():
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    pos = ex.eapiPrivateGetPosition()
    for p in pos:
        if p.get("symbol") == OPTION_BINANCE and (p.get("side") or "").upper() == "LONG":
            return float(p.get("quantity") or 0)
    return 0.0


def market_order(side, qty, reduce_only=False):
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    params = {"symbol": OPTION_BINANCE, "side": side, "type": "MARKET",
              "quantity": str(qty), "reduceOnly": reduce_only}
    return ex.eapiPrivatePostOrder(params)


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stage": "wait", "qty": 0}


def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f)


def main():
    st = load_state()
    stage = st.get("stage", "wait")
    qty = float(st.get("qty", 0))
    log("策略启动，当前状态: stage={}, qty={}".format(stage, qty))

    if stage == "wait":
        # 已持仓则直接进入hold
        held = get_position_qty()
        if held > 0:
            stage, qty = "hold", held
            save_state({"stage": stage, "qty": qty})
            notify("🟢 策略恢复", "检测到已持有 ETH-260911-2575-C {} 张，进入持仓监控".format(qty))
        else:
            notify("📡 策略已启动", "等待 BTC 跌破 {:.0f} 后买入 ETH 9/11 2575-C（90%仓位）\n止盈 ETH ≥ {:.0f}｜止损 ETH ≤ {:.0f}".format(BTC_TRIGGER, ETH_TP, ETH_SL))

    while True:
        try:
            if stage == "wait":
                btc = get_price("BTC/USDT")
                log("等待触发: BTC {:.0f} / 触发线 {:.0f}".format(btc, BTC_TRIGGER))
                if btc <= BTC_TRIGGER:
                    log(">>> BTC {:.0f} 触发!".format(btc))
                    avail = get_opt_available()
                    # 参考市价
                    ex = tools._get_exchange(ACCOUNT)
                    ex.options["defaultType"] = "option"
                    m = ex.eapiPublicGetMark({"symbol": OPTION_BINANCE})
                    ref = float(m[0]["markPrice"])
                    budget = avail * POSITION_PCT
                    qty = int(budget / ref * 100) / 100.0
                    if qty < 0.01:
                        notify("❌ 资金不足", "可用 {:.2f} USDT，无法买入最小 0.01 张".format(avail))
                        time.sleep(60)
                        continue
                    notify("🚀 触发买入", "BTC {:.0f} ≤ {:.0f}，预计买入 {:.2f} 张 @约 {:.2f}（预算 {:.2f} USDT）".format(btc, BTC_TRIGGER, qty, ref, budget))
                    r = market_order("BUY", qty, False)
                    log("买入结果: {}".format(r))
                    time.sleep(3)
                    actual = get_position_qty()
                    if actual <= 0:
                        notify("⚠️ 买入可能未成交", "请检查持仓。下单返回: {}".format(str(r)[:200]))
                        stage = "verify"
                        continue
                    qty = actual
                    stage = "hold"
                    save_state({"stage": stage, "qty": qty})
                    notify("✅ 已买入", "ETH-260911-2575-C {} 张，开始止盈止损监控（TP {} / SL {}）".format(qty, ETH_TP, ETH_SL))
            elif stage == "hold":
                eth = get_price("ETH/USDT")
                log("持仓监控: ETH {:.1f} (TP {} / SL {})".format(eth, ETH_TP, ETH_SL))
                if eth >= ETH_TP:
                    notify("🎯 止盈触发", "ETH {:.1f} ≥ {:.0f}，市价平仓 {} 张".format(eth, ETH_TP, qty))
                    r = market_order("SELL", qty, True)
                    log("平仓结果: {}".format(r))
                    save_state({"stage": "done", "qty": 0})
                    notify("✅ 止盈平仓完成", "结果: {}".format(str(r)[:200]))
                    break
                if eth <= ETH_SL:
                    notify("🛑 止损触发", "ETH {:.1f} ≤ {:.0f}，市价平仓 {} 张".format(eth, ETH_SL, qty))
                    r = market_order("SELL", qty, True)
                    log("平仓结果: {}".format(r))
                    save_state({"stage": "done", "qty": 0})
                    notify("✅ 止损平仓完成", "结果: {}".format(str(r)[:200]))
                    break
            elif stage == "verify":
                # 检查是否买到（可能因价格滑点延迟）
                held = get_position_qty()
                if held > 0:
                    qty = held
                    stage = "hold"
                    save_state({"stage": stage, "qty": qty})
                    notify("✅ 确认持仓", "实际持仓 {} 张，进入监控".format(qty))
                else:
                    log("仍未检测到持仓，继续等待确认…")
                    time.sleep(15)
                    continue
            elif stage == "done":
                log("策略已完成，退出")
                break
        except Exception as e:
            log("错误: {}".format(e))
            notify("⚠️ 策略出错", str(e)[:300])
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
