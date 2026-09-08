# -*- coding: utf-8 -*-
"""
BTC 期权持仓监控 v5（终极修复版）
- WebSocket 实时行情 + 独立轮询兜底（双源并行，绝不真空）
- WS 半开检测：超时无数据强制重连
- 看门狗：数据断流>阈值 → 反复报警（每条消息都含关键词"监控"防拒收）
- BTC 触发价后市价平仓
"""
import os
import time
import threading

os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7899")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7899")

import json
import asyncio
import websockets

from binance_mcp.config import ConfigManager
from binance_mcp.tools import BinanceMCPTools
from notify import send_dingtalk

# ============ 配置 ============
ACCOUNT = "main"
OPTION_BINANCE = "ETH-260911-2475-P"
PRICE_SYMBOL = "ETHUSDT"      # 监控的现货
TP_PRICE = 2470.0    # 价格 <= TP_PRICE 市价止盈平仓
SL_PRICE = None      # 无止损（None=禁用）
WS_ENABLED = False        # 代理节点对WS支持差，默认关；True=尝试WS实时流
POLL_FALLBACK_SECONDS = 1
STALE_ALERT_SEC = 2.0     # 数据中断超过2秒立即报警（用户要求）
REALERT_EVERY = 8         # 断流后每8秒反复提醒
BOOT_GRACE_SEC = 20       # 启动宽限期
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "btc_opt.log")
# ================================

tools = BinanceMCPTools(ConfigManager())
boot_time = time.time()
price = {"val": None, "t": time.time()}
ws_alive = {"ok": False}
done = {"flag": False}
alert_state = {"on": False, "last_alert": 0}
_trigger_lock = threading.Lock()


def log(msg):
    line = "[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify(title, msg):
    # 钉钉机器人有"监控"关键词校验，所有消息必须包含
    title = title if "监控" in title else title + "·监控"
    if "监控" not in msg:
        msg = msg + "\n(监控)"
    try:
        import urllib.request
        import json as _json
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": "### {}\n\n{}".format(title, msg)}}
        req = urllib.request.Request(
            "https://oapi.dingtalk.com/robot/send?access_token=YOUR_DINGTALK_WEBHOOK_TOKEN",
            data=_json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
            ok = data.get("errcode") == 0
            log("钉钉({}): {} - {}".format("OK" if ok else "FAIL:{}".format(data.get("errcode")), title, msg.replace(chr(10), " ")[:80]))
            return ok
    except Exception as e:
        log("钉钉异常: {} - {}".format(e, title))
        return False


def get_qty():
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    for p in ex.eapiPrivateGetPosition():
        if p.get("symbol") == OPTION_BINANCE and (p.get("side") or "").upper() == "LONG":
            return float(p.get("quantity") or 0)
    return 0.0


def close_market(qty):
    ex = tools._get_exchange(ACCOUNT)
    ex.options["defaultType"] = "option"
    return ex.eapiPrivatePostOrder({
        "symbol": OPTION_BINANCE, "side": "SELL", "type": "MARKET",
        "quantity": str(qty), "reduceOnly": True,
    })


def _do_close(kind):
    global done
    try:
        qty = get_qty()
        if qty <= 0:
            notify("ℹ️ 持仓监控提示", "{} 触发但持仓为空（可能已手动平）".format(kind))
        else:
            r = close_market(qty)
            log("平仓结果: {}".format(r))
            notify("✅ {}平仓完成·监控".format(kind), "结果: {}".format(str(r)[:200]))
    except Exception as e:
        notify("❌ {}下单失败·监控".format(kind), str(e)[:200])
    done["flag"] = True


def check_price(px):
    if done["flag"] or px is None:
        return False
    log("价格 {:.2f}（TP {:.0f} / SL {}）".format(px, TP_PRICE, "无" if SL_PRICE is None else "{:.0f}".format(SL_PRICE)))
    if TP_PRICE is not None and px <= TP_PRICE:
        with _trigger_lock:
            if done["flag"]:
                return True
            done["flag"] = True
        notify("🎯 止盈触发·监控", "ETH {:.2f} ≤ {:.0f}，市价平仓".format(px, TP_PRICE))
        _do_close("止盈")
        return True
    if SL_PRICE is not None and px >= SL_PRICE:
        with _trigger_lock:
            if done["flag"]:
                return True
            done["flag"] = True
        notify("🛑 止损触发·监控", "ETH {:.2f} ≥ {:.0f}，市价平仓".format(px, SL_PRICE))
        _do_close("止损")
        return True
    return False


def ws_loop():
    backoff = 2
    while not done["flag"]:
        try:
            async def run():
                async with websockets.connect(WS_URL, proxy="http://127.0.0.1:7899", close_timeout=5, open_timeout=10) as ws:
                    ws_alive["ok"] = True
                    log("WebSocket 已连接（实时行情）")
                    silent = 0
                    while not done["flag"]:
                        try:
                            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                            px = float(msg.get("p"))
                            price["val"], price["t"] = px, time.time()
                            silent = 0
                            if check_price(px):
                                return
                        except asyncio.TimeoutError:
                            silent += 1
                            if silent >= 2:
                                log("WebSocket 16秒无数据，判定半开连接，强制重连")
                                return
            asyncio.run(run())
            backoff = 2
        except Exception as e:
            log("WebSocket 断开: {}，{}秒后重连…".format(str(e)[:80], backoff))
            ws_alive["ok"] = False
            time.sleep(backoff)
            backoff = min(backoff * 2, 15)


def poll_fallback():
    """主数据源：每2秒轮询一次（短连接，代理节点稳定）。"""
    while not done["flag"]:
        try:
            ex = tools._get_exchange(ACCOUNT)
            t = ex.fapiPublicGetTickerPrice({"symbol": PRICE_SYMBOL})
            px = float(t["price"])
            price["val"], price["t"] = px, time.time()
            if check_price(px):
                break
        except Exception:
            pass
        time.sleep(POLL_FALLBACK_SECONDS)


def watchdog():
    """看门狗：数据断流>4秒 → 反复报警直到恢复。"""
    while not done["flag"]:
        try:
            staleness = time.time() - price["t"]
            limit = BOOT_GRACE_SEC if (time.time() - boot_time) < BOOT_GRACE_SEC else STALE_ALERT_SEC
            if staleness > limit:
                if not alert_state["on"]:
                    alert_state["on"] = True
                    alert_state["last_alert"] = time.time()
                    notify("🚨🚨 监控中断警报", "行情流已中断 {} 秒！止盈止损保护失效！\n请立即检查网络/代理节点！".format(int(staleness)))
                elif time.time() - alert_state["last_alert"] >= REALERT_EVERY:
                    alert_state["last_alert"] = time.time()
                    notify("🔁🔁 监控仍在中断", "行情流中断已持续 {} 秒，保护仍失效！请马上处理！".format(int(staleness)))
            else:
                if alert_state["on"]:
                    alert_state["on"] = False
                    notify("✅ 监控已恢复", "行情流恢复（中断约 {} 秒），继续实时盯盘".format(int(staleness)))
        except Exception:
            pass
        time.sleep(1)


def main():
    # 启动时网络可能不通：反复重试拿持仓，直到成功
    while True:
        try:
            qty = get_qty()
            break
        except Exception as e:
            log("启动获取持仓失败（网络？）: {}，10秒后重试…".format(str(e)[:80]))
            time.sleep(10)
    if qty <= 0:
        log("未检测到持仓 {}，退出".format(OPTION_BINANCE))
        notify("⚠️ 监控未启动", "未检测到 {} 持仓".format(OPTION_BINANCE))
        return
    log("启动实时监控 v5：持仓 {} 张，TP {}<={:.0f} / SL {}".format(qty, PRICE_SYMBOL, TP_PRICE, "无" if SL_PRICE is None else ">={:.0f}".format(SL_PRICE)))
    notify("📡 实时监控启动(v5)", "持仓 {} 张 {}｜价格≤{:.0f}市价平仓{}\n中断>{}秒将反复报警".format(
        qty, OPTION_BINANCE, TP_PRICE, "" if SL_PRICE is None else "｜价格≥{:.0f}止损".format(SL_PRICE), int(STALE_ALERT_SEC)))
    threads = []
    if WS_ENABLED:
        threads.append(threading.Thread(target=ws_loop, daemon=True))
    threads.append(threading.Thread(target=poll_fallback, daemon=True))
    threads.append(threading.Thread(target=watchdog, daemon=True))
    for t in threads:
        t.start()
    while not done["flag"]:
        time.sleep(1)
    log("监控结束")


if __name__ == "__main__":
    main()
