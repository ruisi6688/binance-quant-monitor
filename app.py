# -*- coding: utf-8 -*-
import os

# 代理：FlClash 本地端口，币安访问走这里（代码内兜底，也可用环境变量覆盖）
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7899")
os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7899")

from flask import Flask, jsonify, request, send_from_directory

from binance_mcp.config import ConfigManager
from binance_mcp.tools import BinanceMCPTools
from notify import send_dingtalk

app = Flask(__name__, static_folder="static", static_url_path="")

cm = ConfigManager()
tools = BinanceMCPTools(cm)

DEFAULT_ACCOUNT = "main"

WATCH_SYMBOLS = [
    ("BTC", "BTC/USDT"),
    ("ETH", "ETH/USDT"),
    ("SOL", "SOL/USDT"),
    ("BNB", "BNB/USDT"),
    ("XRP", "XRP/USDT"),
    ("DOGE", "DOGE/USDT"),
    ("ADA", "ADA/USDT"),
    ("LTC", "LTC/USDT"),
]


def _json_ok(data):
    return jsonify({"success": True, "data": data})


def _json_err(e):
    return jsonify({"success": False, "error": str(e)}), 200


def _call(fn, *args, **kwargs):
    try:
        return _json_ok(fn(*args, **kwargs))
    except Exception as e:
        return _json_err(e)


def _summarize_balance(raw):
    """把 ccxt 余额结果整理成 [{asset, free, used, total}]，只保留非零资产。"""
    items = []
    if not isinstance(raw, dict):
        return items
    for key, val in raw.items():
        if key in ("info", "free", "used", "total", "timestamp", "datetime"):
            continue
        if isinstance(val, dict) and ("free" in val or "total" in val):
            free = float(val.get("free", 0) or 0)
            used = float(val.get("used", 0) or 0)
            total = float(val.get("total", 0) or 0)
            if total > 0 or free > 0 or used > 0:
                items.append({"asset": key, "free": free, "used": used, "total": total})
    items.sort(key=lambda x: -x["total"])
    return items


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/accounts")
def accounts():
    return _json_ok(list(cm.list_accounts().keys()))


@app.route("/api/tickers")
def tickers():
    out = []
    for base, symbol in WATCH_SYMBOLS:
        try:
            t = tools.get_ticker(symbol)
            out.append({
                "base": base,
                "symbol": symbol,
                "last": t.get("last"),
                "change": t.get("percentage") or t.get("change"),
                "high": t.get("high"),
                "low": t.get("low"),
                "volume": t.get("quoteVolume") or t.get("baseVolume"),
            })
        except Exception:
            out.append({"base": base, "symbol": symbol, "error": True})
    return _json_ok(out)


@app.route("/api/ticker")
def ticker():
    symbol = request.args.get("symbol", "BTC/USDT")
    return _call(tools.get_ticker, symbol)


@app.route("/api/klines")
def klines():
    symbol = request.args.get("symbol", "BTC/USDT")
    timeframe = request.args.get("timeframe", "1h")
    limit = int(request.args.get("limit", 200))
    return _call(tools.get_klines, symbol, timeframe, None, limit)


@app.route("/api/orderbook")
def orderbook():
    symbol = request.args.get("symbol", "BTC/USDT")
    limit = int(request.args.get("limit", 20))
    return _call(tools.get_order_book, symbol, limit)


@app.route("/api/funding")
def funding():
    symbol = request.args.get("symbol", "BTC/USDT:USDT")
    return _call(tools.get_funding_rate, symbol)


@app.route("/api/balance")
def balance():
    acct = request.args.get("account_id", DEFAULT_ACCOUNT)
    typ = request.args.get("type", "spot")
    raw = tools.get_balance(acct, typ)
    try:
        return _json_ok(_summarize_balance(raw))
    except Exception:
        return _json_ok(raw)


@app.route("/api/positions")
def positions():
    acct = request.args.get("account_id", DEFAULT_ACCOUNT)
    return _call(tools.get_positions, acct)


@app.route("/api/futures_positions")
def futures_positions():
    acct = request.args.get("account_id", DEFAULT_ACCOUNT)
    return _call(tools.get_futures_positions, acct)


@app.route("/api/open_orders")
def open_orders():
    acct = request.args.get("account_id", DEFAULT_ACCOUNT)
    symbol = request.args.get("symbol") or None
    return _call(tools.get_open_orders, acct, symbol)


@app.route("/api/my_trades")
def my_trades():
    acct = request.args.get("account_id", DEFAULT_ACCOUNT)
    symbol = request.args.get("symbol") or None
    return _call(tools.get_my_trades, acct, symbol, None, 100)


@app.route("/api/order", methods=["POST"])
def order():
    body = request.get_json(force=True) or {}
    acct = body.get("account_id", DEFAULT_ACCOUNT)
    market = body.get("market", "spot")
    symbol = body["symbol"]
    side = body["side"]
    amount = float(body.get("amount", 0))
    order_type = body.get("order_type", "market")
    price = body.get("price")
    if price not in (None, ""):
        price = float(price)
    try:
        if market == "futures":
            resp = tools.create_contract_order(acct, symbol, side, amount, order_type, price, "future")
        else:
            resp = tools.create_spot_order(acct, symbol, side, amount, order_type, price)
    except Exception as e:
        send_dingtalk("❌ 下单失败", "市场: {}\n交易对: {}\n方向: {}\n数量: {}\n错误: {}".format(market, symbol, side, amount, str(e)[:200]))
        raise
    send_dingtalk("📤 下单成功", "市场: {}\n交易对: {}\n方向: {}\n类型: {}\n价格: {}\n数量: {}\n返回: {}".format(
        market, symbol, side, order_type, price, amount, str(resp)[:200]))
    return _json_ok(resp)


# ==================== 期权 ====================
import time as _time

_opt_cache = {"contracts": None, "marks": None, "ts": 0}


def _opt_exchange(acct=DEFAULT_ACCOUNT):
    ex = tools._get_exchange(acct)
    ex.options["defaultType"] = "option"
    return ex


def _opt_data(force=False):
    if force or _opt_cache["ts"] == 0 or _time.time() - _opt_cache["ts"] > 15:
        ex = _opt_exchange()
        _opt_cache["contracts"] = ex.eapiPublicGetExchangeInfo().get("optionSymbols") or []
        _opt_cache["marks"] = ex.eapiPublicGetMark() or []
        _opt_cache["ts"] = _time.time()
    return _opt_cache["contracts"], _opt_cache["marks"]


def _mark_map():
    _, marks = _opt_data()
    return {m["symbol"]: m for m in marks}


@app.route("/api/option_chain")
def option_chain():
    try:
        contracts, marks = _opt_data()
        underlying = request.args.get("underlying", "ETH").upper()
        mm = {m["symbol"]: m for m in marks}
        rows = {}
        for c in contracts:
            if not (c.get("underlying") or "").startswith(underlying):
                continue
            sym = c["symbol"]
            mk = mm.get(sym, {})
            strike = c.get("strikePrice")
            expiry = c.get("expiryDate")
            side = c.get("side")
            node = rows.setdefault(str(expiry), {}).setdefault(str(strike), {"strike": strike})
            node[side] = {
                "symbol": sym, "side": side,
                "mark": float(mk.get("markPrice") or 0),
                "delta": float(mk.get("delta") or 0),
                "gamma": float(mk.get("gamma") or 0),
                "theta": float(mk.get("theta") or 0),
                "vega": float(mk.get("vega") or 0),
                "iv": float(mk.get("markIV") or 0),
                "bidIv": float(mk.get("bidIV") or 0),
                "askIv": float(mk.get("askIV") or 0),
            }
        result = []
        for exp, strikes in rows.items():
            sl = []
            for s in sorted(strikes.keys(), key=lambda x: float(x)):
                d = strikes[s]
                d["strike"] = s
                sl.append(d)
            result.append({"expiry": int(exp), "strikes": sl})
        result.sort(key=lambda x: x["expiry"])
        return _json_ok(result)
    except Exception as e:
        return _json_err(e)


@app.route("/api/option_positions")
def option_positions():
    acct = request.args.get("account_id", DEFAULT_ACCOUNT)
    try:
        ex = _opt_exchange(acct)
        positions = ex.fetch_option_positions(None) or []
        mm = _mark_map()
        out = []
        for p in positions:
            info = p.get("info") or {}
            bsym = info.get("symbol")
            mk = mm.get(bsym, {})
            side = (p.get("side") or "long").lower()
            entry = float(p.get("entryPrice") or 0)
            contracts = float(p.get("contracts") or 0)
            mark = float(p.get("markPrice") or mk.get("markPrice") or 0)
            pnl = p.get("unrealizedPnl")
            if pnl is None:
                pnl = (mark - entry) * contracts if side == "long" else (entry - mark) * contracts
            strike = float(info.get("strikePrice") or 0)
            be = (entry + strike) if side == "long" else (strike - entry)
            out.append({
                "symbol": p.get("symbol"),
                "binance_symbol": bsym,
                "optionSide": info.get("optionSide") or info.get("side"),
                "side": side,
                "contracts": contracts,
                "entryPrice": entry,
                "markPrice": mark,
                "unrealizedPnl": pnl,
                "strikePrice": strike,
                "expiryDate": info.get("expiryDate"),
                "delta": float(mk.get("delta") or 0),
                "gamma": float(mk.get("gamma") or 0),
                "theta": float(mk.get("theta") or 0),
                "vega": float(mk.get("vega") or 0),
                "iv": float(mk.get("markIV") or 0),
            })
        return _json_ok(out)
    except Exception as e:
        return _json_err(e)


@app.route("/api/option_open_orders")
def option_open_orders():
    acct = request.args.get("account_id", DEFAULT_ACCOUNT)
    try:
        ex = _opt_exchange(acct)
        oo = ex.eapiPrivateGetOpenOrders() or []
        out = []
        for o in oo:
            out.append({
                "orderId": o.get("orderId"), "symbol": o.get("symbol"),
                "side": o.get("side"), "type": o.get("type"),
                "price": o.get("price"), "quantity": o.get("quantity"),
                "reduceOnly": o.get("reduceOnly"), "status": o.get("status"),
                "stopPrice": o.get("stopPrice"), "createTime": o.get("createTime"),
            })
        return _json_ok(out)
    except Exception as e:
        return _json_err(e)


@app.route("/api/option_tpsl", methods=["POST"])
def option_tpsl():
    body = request.get_json(force=True) or {}
    acct = body.get("account_id", DEFAULT_ACCOUNT)
    symbol = body.get("symbol")
    action = body.get("action", "tp")
    try:
        ex = _opt_exchange(acct)
        positions = ex.fetch_option_positions(None) or []
        pos = next((p for p in positions if p.get("symbol") == symbol), None)
        if not pos:
            return _json_err("未找到该期权持仓")
        info = pos.get("info") or {}
        bsym = info.get("symbol")
        pos_side = (pos.get("side") or "long").lower()
        close_side = "SELL" if pos_side == "long" else "BUY"
        qty = float(body.get("amount") or pos.get("contracts") or 0)
        if action == "tp":
            price = float(body.get("price") or 0)
            params = {"symbol": bsym, "side": close_side, "type": "LIMIT",
                      "quantity": str(qty), "price": str(price),
                      "reduceOnly": True, "timeInForce": "GTC"}
        else:
            stop = float(body.get("stop_price") or 0)
            params = {"symbol": bsym, "side": close_side, "type": "STOP_LOSS",
                      "quantity": str(qty), "stopPrice": str(stop), "reduceOnly": True}
        resp = ex.eapiPrivatePostOrder(params)
        send_dingtalk("🎯 期权止盈止损设置", "{}\n方向: {}\n数量: {}\n动作: {}\n价格/触发: {}\n订单号: {}".format(
            bsym, close_side, qty, action, body.get("price") or body.get("stop_price"),
            resp.get("orderId") if isinstance(resp, dict) else resp))
        return _json_ok(resp)
    except Exception as e:
        send_dingtalk("❌ 期权止盈止损设置失败", "{}\n动作: {}\n错误: {}".format(symbol, action, str(e)[:200]))
        return _json_err(e)


@app.route("/api/option_cancel", methods=["POST"])
def option_cancel():
    body = request.get_json(force=True) or {}
    acct = body.get("account_id", DEFAULT_ACCOUNT)
    order_id = body.get("order_id")
    symbol = body.get("symbol")
    try:
        ex = _opt_exchange(acct)
        resp = ex.eapiPrivateDeleteOrder({"symbol": symbol, "orderId": order_id})
        send_dingtalk("🗑️ 撤单", "合约: {}\n订单号: {}\n结果: {}".format(symbol, order_id, str(resp)[:150]))
        return _json_ok(resp)
    except Exception as e:
        send_dingtalk("❌ 撤单失败", "合约: {}\n订单号: {}\n错误: {}".format(symbol, order_id, str(e)[:150]))
        return _json_err(e)


@app.route("/api/option_info")
def option_info():
    symbol = request.args.get("symbol")
    try:
        ex = _opt_exchange()
        m = ex.eapiPublicGetMark({"symbol": symbol})
        return _json_ok(m[0] if m else {})
    except Exception as e:
        return _json_err(e)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8900, debug=False)
