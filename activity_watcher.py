# -*- coding: utf-8 -*-
"""
账户活动监控：定期对比期权持仓/挂单快照，发现变化（开仓/平仓/挂单/撤单/成交）
即推送钉钉 —— 覆盖所有渠道的操作（脚本/面板/手机/API）。
"""
import os
import time

os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7899")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7899")

from binance_mcp.config import ConfigManager
from binance_mcp.tools import BinanceMCPTools
from notify import send_dingtalk

ACCOUNT = "main"
POLL_SECONDS = 30
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "activity.log")

tools = BinanceMCPTools(ConfigManager())

_prev_pos = {}
_prev_orders = {}


def log(msg):
    line = "[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify(title, msg):
    ok = send_dingtalk(title, msg)
    log("钉钉({}): {} - {}".format("OK" if ok else "FAIL", title, msg))


def get_snapshot():
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    pos = {}
    for p in ex.eapiPrivateGetPosition():
        q = float(p.get("quantity") or 0)
        if q > 0:
            pos[p["symbol"]] = {
                "side": (p.get("side") or "").upper(),
                "qty": q,
                "entry": p.get("entryPrice"),
                "mark": p.get("markPrice"),
            }
    orders = {}
    for o in ex.eapiPrivateGetOpenOrders():
        orders[o["orderId"]] = {
            "symbol": o.get("symbol"), "side": o.get("side"), "type": o.get("type"),
            "price": o.get("price"), "qty": o.get("quantity"),
        }
    return pos, orders


def fmt_change(msg):
    return msg.replace("\n", "\\n")


def diff():
    global _prev_pos, _prev_orders
    msgs = []
    try:
        pos, orders = get_snapshot()
    except Exception as e:
        log("快照失败: {}".format(str(e)[:100]))
        return
    # 持仓变化
    for sym, d in pos.items():
        if sym not in _prev_pos:
            msgs.append("🟢 新开仓: {} {} {} 张 (入场 {})".format(sym, d["side"], d["qty"], d.get("entry")))
        elif _prev_pos[sym]["qty"] != d["qty"]:
            msgs.append("🔁 仓位变动: {} {} → {} 张".format(sym, _prev_pos[sym]["qty"], d["qty"]))
    for sym, d in _prev_pos.items():
        if sym not in pos:
            msgs.append("🔴 平仓: {} ({}) 已清仓".format(sym, d["side"]))
    # 挂单变化
    for oid, d in orders.items():
        if oid not in _prev_orders:
            msgs.append("📌 新挂单: {} {} {} @{} x{} (单号{})".format(d["symbol"], d["side"], d["type"], d["price"], d["qty"], oid))
    for oid, d in _prev_orders.items():
        if oid not in orders:
            msgs.append("🗑️ 委托取消/成交: {} {} (单号{})".format(d["symbol"], d["side"], oid))
    _prev_pos, _prev_orders = pos, orders
    if msgs:
        notify("🔔 账户活动", "\n".join(msgs)[:1500])


def main():
    # 初始化基线（不通知）
    try:
        _prev_pos, _prev_orders = get_snapshot()
        log("活动监控启动，基线: {} 持仓, {} 挂单".format(len(_prev_pos), len(_prev_orders)))
        notify("📡 账户活动监控已启动", "持仓/挂单/成交变化将实时推送（含手机操作）")
    except Exception as e:
        log("启动失败: {}".format(str(e)[:150]))
        return
    while True:
        try:
            diff()
        except Exception as e:
            log("错误: {}".format(str(e)[:100]))
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
