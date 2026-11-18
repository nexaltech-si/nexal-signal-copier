"""
In-memory stand-in for the MT5 REST bridge (mt5/app), for simulated sessions.

It speaks the bridge's HTTP API, so the real MT5RestProvider runs against it
unchanged, and follows the same MT5 rules the bridge does:
  • a position gets the ticket of the order that opened it
  • /modify_sl_tp and /modify_order keep a stop that is not sent; 0 removes it
  • a pending limit fills when price reaches it; SL / TP close a position

`tick(bid)` moves the market and runs fills and stops. Nothing here talks to a
broker: it proves the bot's order handling, not broker behaviour.
"""
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from aiohttp import web

SYMBOL = "XAUUSD"
CONTRACT = 100.0          # 1 lot gold = 100 oz → 1.00 price move = $100 per lot
SPREAD = 0.30

# name → contract size, spread, digits, tick value (USD per tick per lot), start bid
SYMBOLS = {
    "XAUUSD": dict(contract=100.0, spread=0.30, digits=2, tick_value=1.0, bid=3945.0),
    "XAGUSD": dict(contract=5000.0, spread=0.03, digits=3, tick_value=5.0, bid=48.500),
    "EURUSD": dict(contract=100000.0, spread=0.00010, digits=5, tick_value=1.0, bid=1.08500),
    "GBPUSD": dict(contract=100000.0, spread=0.00012, digits=5, tick_value=1.0, bid=1.27000),
    "BTCUSD": dict(contract=1.0, spread=12.0, digits=2, tick_value=0.01, bid=98500.0),
    "US30": dict(contract=1.0, spread=2.0, digits=1, tick_value=0.1, bid=44200.0),
}

ORDER_TYPES = {"BUY_LIMIT": 2, "SELL_LIMIT": 3, "BUY_STOP": 4, "SELL_STOP": 5}


class FakeMT5Bridge:
    def __init__(self, bid: float = 3945.0, balance: float = 10000.0):
        self.symbols = {name: dict(spec) for name, spec in SYMBOLS.items()}
        self.symbols[SYMBOL]["bid"] = bid
        self.balance = balance
        self.positions: Dict[int, dict] = {}
        self.orders: Dict[int, dict] = {}
        self.closed: List[dict] = []
        self.deals: Dict[int, List[dict]] = {}     # position ticket → its IN / OUT deals
        self.cancelled: Dict[int, dict] = {}       # pending orders that were cancelled
        self.log: List[str] = []          # every write the bot made, in order
        self._ticket = 500000
        self._runner = None

    # ── market ───────────────────────────────────────────────────────────────
    @property
    def bid(self) -> float:                      # gold, for single-symbol sessions
        return self.symbols[SYMBOL]["bid"]

    @property
    def ask(self) -> float:
        return self.ask_of(SYMBOL)

    def spec(self, symbol: str) -> dict:
        return self.symbols[symbol]

    def bid_of(self, symbol: str) -> float:
        return self.symbols[symbol]["bid"]

    def ask_of(self, symbol: str) -> float:
        sp = self.symbols[symbol]
        return round(sp["bid"] + sp["spread"], sp["digits"])

    def _next(self) -> int:
        self._ticket += 1
        return self._ticket

    def _profit(self, p: dict, price: Optional[float] = None) -> float:
        sym = p["symbol"]
        px = price if price is not None else (self.bid_of(sym) if p["type"] == 0 else self.ask_of(sym))
        diff = (px - p["price_open"]) if p["type"] == 0 else (p["price_open"] - px)
        return round(diff * self.symbols[sym]["contract"] * p["volume"], 2)

    def _deal(self, p: dict, entry: str, price: float, volume: float, profit: float = 0.0) -> None:
        side = ("BUY" if p["type"] == 0 else "SELL") if entry == "IN" else ("SELL" if p["type"] == 0 else "BUY")
        now = datetime.now(timezone.utc).isoformat()
        self.deals.setdefault(p["ticket"], []).append({
            "ticket": self._next(), "order": p["ticket"], "time": now, "time_msc": now, "type": side,
            "entry": entry, "magic": p["magic"], "position_id": p["ticket"], "volume": volume, "price": price,
            "commission": 0.0, "swap": 0.0, "profit": profit, "fee": 0.0, "symbol": p["symbol"],
            "comment": p.get("comment", "")})

    def _close(self, ticket: int, price: float, reason: str, volume: Optional[float] = None) -> None:
        p = self.positions[ticket]
        vol = volume if volume and volume < p["volume"] else p["volume"]
        part = dict(p, volume=vol)
        profit = self._profit(part, price)
        self.balance = round(self.balance + profit, 2)
        self._deal(p, "OUT", price, vol, profit)
        self.closed.append(dict(part, price_close=price, profit=profit, reason=reason, time_close=time.time()))
        if vol < p["volume"]:
            p["volume"] = round(p["volume"] - vol, 2)
        else:
            del self.positions[ticket]

    def tick(self, bid: float, symbol: str = SYMBOL) -> List[str]:
        """Move `symbol` to `bid`; returns what the broker did (fills, SL / TP closes)."""
        self.symbols[symbol]["bid"] = round(bid, self.symbols[symbol]["digits"])
        s_bid, s_ask = self.bid_of(symbol), self.ask_of(symbol)
        events = []
        for t, o in list(self.orders.items()):
            if o["symbol"] != symbol:
                continue
            sell = o["type"] in (3, 5)
            hit = (s_bid >= o["price_open"]) if o["type"] == 3 else \
                  (s_ask <= o["price_open"]) if o["type"] == 2 else \
                  (s_ask >= o["price_open"]) if o["type"] == 4 else (s_bid <= o["price_open"])
            if hit:
                del self.orders[t]
                self.positions[t] = dict(ticket=t, symbol=o["symbol"], type=1 if sell else 0,
                                         volume=o["volume_current"], price_open=o["price_open"],
                                         sl=o["sl"], tp=o["tp"], magic=o["magic"], comment=o["comment"],
                                         time=time.time())
                self._deal(self.positions[t], "IN", o["price_open"], o["volume_current"])
                events.append(f"pending #{t} filled at {o['price_open']}")
        for t, p in list(self.positions.items()):
            if p["symbol"] != symbol:
                continue
            buy = p["type"] == 0
            px = s_bid if buy else s_ask
            if p["sl"] and ((px <= p["sl"]) if buy else (px >= p["sl"])):
                self._close(t, p["sl"], "SL")
                events.append(f"position #{t} closed at SL {p['sl']} ({self.closed[-1]['profit']:+.2f})")
            elif p["tp"] and ((px >= p["tp"]) if buy else (px <= p["tp"])):
                self._close(t, p["tp"], "TP")
                events.append(f"position #{t} closed at TP {p['tp']} ({self.closed[-1]['profit']:+.2f})")
        return events

    # ── views ────────────────────────────────────────────────────────────────
    def _pos_view(self, p: dict) -> dict:
        current = self.bid_of(p["symbol"]) if p["type"] == 0 else self.ask_of(p["symbol"])
        return dict(p, price_current=current, profit=self._profit(p), swap=0.0)

    # ── what a person does in the MT5 terminal, bypassing the bot ────────────
    def manual_close(self, ticket: int) -> None:
        p = self.positions[ticket]
        self._close(ticket, self.bid_of(p["symbol"]) if p["type"] == 0 else self.ask_of(p["symbol"]), "manual")

    def manual_cancel(self, ticket: int) -> None:
        self.cancelled[ticket] = self.orders.pop(ticket)

    def flatten(self) -> None:
        """Close every position at market and cancel every pending order."""
        for t in list(self.positions):
            self.manual_close(t)
        for t in list(self.orders):
            self.manual_cancel(t)

    # ── HTTP handlers ────────────────────────────────────────────────────────
    async def health(self, _):
        return web.json_response({"status": "healthy", "mt5_connected": True, "mt5_initialized": True})

    async def account_info(self, _):
        floating = sum(self._profit(p) for p in self.positions.values())
        return web.json_response({"login": 990001, "balance": self.balance, "equity": round(self.balance + floating, 2),
                                  "margin": 0.0, "margin_free": self.balance, "currency": "USD", "leverage": 500,
                                  "server": "Simulated-Demo", "name": "Simulated account", "trade_allowed": True})

    async def symbol_list(self, _):
        return web.json_response(list(self.symbols))

    async def symbol_info(self, request):
        name = request.match_info["s"]
        sp = self.symbols.get(name)
        if not sp:
            return web.json_response({"error": f"Symbol {name} NOT FOUND"}, status=404)
        point = 10 ** -sp["digits"]
        return web.json_response({"name": name, "digits": sp["digits"], "point": point, "trade_tick_size": point,
                                  "trade_tick_value": sp["tick_value"], "trade_contract_size": sp["contract"],
                                  "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
                                  "spread": int(round(sp["spread"] / point)), "trade_stops_level": 0,
                                  "visible": True, "bid": self.bid_of(name), "ask": self.ask_of(name)})

    async def tick_info(self, request):
        name = request.match_info["s"]
        if name not in self.symbols:
            return web.json_response({"error": f"No tick for symbol {name} NOT FOUND"}, status=404)
        return web.json_response({"bid": self.bid_of(name), "ask": self.ask_of(name), "last": self.bid_of(name),
                                  "time": int(time.time())})

    async def get_positions(self, _):
        return web.json_response([self._pos_view(p) for p in self.positions.values()])

    async def get_orders(self, _):
        return web.json_response(list(self.orders.values()))

    async def order(self, request):
        b = await request.json()
        buy = str(b["type"]).upper() == "BUY"
        if b["symbol"] not in self.symbols:
            return web.json_response({"error": f"Symbol {b['symbol']} NOT FOUND"}, status=400)
        t, price = self._next(), (self.ask_of(b["symbol"]) if buy else self.bid_of(b["symbol"]))
        self.positions[t] = dict(ticket=t, symbol=b["symbol"], type=0 if buy else 1, volume=float(b["volume"]),
                                 price_open=price, sl=float(b.get("sl") or 0), tp=float(b.get("tp") or 0),
                                 magic=int(b.get("magic") or 0), comment=b.get("comment", ""), time=time.time())
        self._deal(self.positions[t], "IN", price, float(b["volume"]))
        self.log.append(f"MARKET {b['type']} {b['volume']} @ {price} SL {b.get('sl')} TP {b.get('tp')} → #{t}")
        return web.json_response({"message": "Order executed", "result": {
            "retcode": 10009, "order": t, "deal": self._next(), "volume": float(b["volume"]), "price": price}})

    async def limit_order(self, request):
        b = await request.json()
        kind = str(b.get("type") or b.get("order_type")).upper()
        t = self._next()
        self.orders[t] = dict(ticket=t, symbol=b["symbol"], type=ORDER_TYPES[kind], volume_initial=float(b["volume"]),
                              volume_current=float(b["volume"]), price_open=float(b["price"]),
                              sl=float(b.get("sl") or 0), tp=float(b.get("tp") or 0), magic=int(b.get("magic") or 0),
                              comment=b.get("comment", ""), time_setup=time.time())
        self.log.append(f"PENDING {kind} {b['volume']} @ {b['price']} SL {b.get('sl')} TP {b.get('tp')} → #{t}")
        return web.json_response({"message": "Order placed", "result": {
            "retcode": 10009, "order": t, "deal": 0, "volume": float(b["volume"]), "price": float(b["price"])}})

    async def modify_sl_tp(self, request):
        b = await request.json()
        p = self.positions.get(int(b["position"]))
        if not p:
            return web.json_response({"error": f"Position {b['position']} not found"}, status=400)
        new_sl = float(b["sl"]) if b.get("sl") is not None else p["sl"]      # not sent → kept
        new_tp = float(b["tp"]) if b.get("tp") is not None else p["tp"]      # 0 → removed
        if new_sl == p["sl"] and new_tp == p["tp"]:
            return web.json_response({"error": "No changes", "retcode": 10025}, status=400)
        self.log.append(f"MODIFY position #{p['ticket']}: SL {p['sl']} → {new_sl}, TP {p['tp']} → {new_tp}")
        p["sl"], p["tp"] = new_sl, new_tp
        return web.json_response({"message": "SL/TP updated", "result": {"retcode": 10009}})

    async def modify_order(self, request):
        b = await request.json()
        o = self.orders.get(int(b["ticket"]))
        if not o:
            return web.json_response({"error": f"Order {b['ticket']} not found"}, status=400)
        new_sl = float(b["sl"]) if b.get("sl") is not None else o["sl"]
        new_tp = float(b["tp"]) if b.get("tp") is not None else o["tp"]
        new_px = float(b["price"]) if b.get("price") is not None else o["price_open"]
        self.log.append(f"MODIFY order #{o['ticket']}: SL {o['sl']} → {new_sl}, TP {o['tp']} → {new_tp}, "
                        f"price {o['price_open']} → {new_px}")
        o["sl"], o["tp"], o["price_open"] = new_sl, new_tp, new_px
        return web.json_response({"message": "Order modified", "result": {"retcode": 10009}})

    async def cancel_order(self, request):
        b = await request.json()
        order = self.orders.pop(int(b["ticket"]), None)
        if order is None:
            return web.json_response({"error": "Order not found", "retcode": 10013}, status=400)
        self.cancelled[order["ticket"]] = order
        self.log.append(f"CANCEL order #{b['ticket']}")
        return web.json_response({"message": "Order cancelled", "result": {"retcode": 10009}})

    async def close_position(self, request):
        b = await request.json()
        t = int(b["position"]["ticket"])
        if t not in self.positions:
            return web.json_response({"error": f"Position {t} not found"}, status=400)
        p = self.positions[t]
        price = self.bid_of(p["symbol"]) if p["type"] == 0 else self.ask_of(p["symbol"])
        vol = float(b["volume"]) if b.get("volume") else None
        self._close(t, price, "bot", vol)
        self.log.append(f"CLOSE position #{t} {vol or p['volume']} lots @ {price} ({self.closed[-1]['profit']:+.2f})")
        return web.json_response({"message": "Position closed", "result": {
            "retcode": 10009, "order": self._next(), "deal": self._next(), "price": price,
            "volume": vol or p["volume"]}})

    # ── trade lifecycle (what order sync reads to learn how a trade ended) ───
    def _status(self, ticket: int) -> dict:
        if ticket in self.orders:
            o = self.orders[ticket]
            return {"ticket": ticket, "status": "PENDING", "is_open": True, "symbol": o["symbol"],
                    "price_open": o["price_open"], "sl": o["sl"], "tp": o["tp"]}
        if ticket in self.positions:
            p = self._pos_view(self.positions[ticket])
            return {"ticket": ticket, "status": "RUNNING", "is_open": True, "current_profit": p["profit"],
                    "current_swap": 0.0, "symbol": p["symbol"], "type": "BUY" if p["type"] == 0 else "SELL",
                    "price_open": p["price_open"], "price_current": p["price_current"], "sl": p["sl"],
                    "tp": p["tp"], "volume": p["volume"]}
        deals = self.deals.get(ticket, [])
        if deals:
            net = sum(d["profit"] for d in deals)
            status = "CLOSED_PROFIT" if net > 0.01 else "CLOSED_LOSS" if net < -0.01 else "CLOSED_BREAKEVEN"
            return {"ticket": ticket, "status": status, "is_open": False, "total_profit": net,
                    "total_commission": 0.0, "total_swap": 0.0, "net_pnl": net, "symbol": deals[0]["symbol"],
                    "type": deals[0]["type"]}
        if ticket in self.cancelled:
            return {"ticket": ticket, "status": "CANCELED", "is_open": False, "symbol": self.cancelled[ticket]["symbol"]}
        return {"ticket": ticket, "status": "UNKNOWN", "is_open": False}

    async def trade_status(self, request):
        return web.json_response(self._status(int(request.query["ticket"])))

    async def trade_batch_status(self, request):
        b = await request.json()
        return web.json_response({"results": [self._status(int(t)) for t in b["tickets"]]})

    async def trade_lifecycle(self, request):
        ticket = int(request.query["ticket"])
        status, deals = self._status(ticket), self.deals.get(ticket, [])
        summary = {"ticket": ticket, "status": status["status"], "total_deals": len(deals),
                   "total_profit": sum(d["profit"] for d in deals), "total_commission": 0.0, "total_swap": 0.0,
                   "total_volume": sum(d["volume"] for d in deals), "net_pnl": sum(d["profit"] for d in deals)}
        ins, outs = [d for d in deals if d["entry"] == "IN"], [d for d in deals if d["entry"] == "OUT"]
        if ins:
            summary.update(entry_price=ins[0]["price"], entry_time=ins[0]["time"])
        if outs:
            summary.update(exit_price=outs[-1]["price"], exit_time=outs[-1]["time"])
        position = self._pos_view(self.positions[ticket]) if ticket in self.positions else None
        history = dict(self.cancelled[ticket], state="CANCELED") if ticket in self.cancelled else None
        return web.json_response({"status": status["status"], "pending_order": self.orders.get(ticket),
                                  "position": position, "order_history": history, "deals": deals,
                                  "summary": summary})

    async def trade_search(self, _):
        return web.json_response({"trades": [], "count": 0})

    async def unknown(self, request):
        self.log.append(f"?? unhandled {request.method} {request.path}")
        return web.json_response({"error": f"not simulated: {request.path}"}, status=404)

    # ── server ───────────────────────────────────────────────────────────────
    async def start(self, port: int = 5055) -> str:
        app = web.Application()
        app.add_routes([
            web.get("/health", self.health), web.get("/account_info", self.account_info),
            web.get("/symbols", self.symbol_list), web.get("/symbol_info/{s}", self.symbol_info),
            web.get("/symbol_info_tick/{s}", self.tick_info),
            web.get("/get_positions", self.get_positions), web.get("/get_orders", self.get_orders),
            web.post("/order", self.order), web.post("/limit_order", self.limit_order),
            web.post("/modify_sl_tp", self.modify_sl_tp), web.post("/modify_order", self.modify_order),
            web.post("/cancel_order", self.cancel_order),
            web.get("/trade_status", self.trade_status), web.post("/trade_batch_status", self.trade_batch_status),
            web.get("/trade_lifecycle", self.trade_lifecycle), web.get("/trade_search", self.trade_search),
            web.post("/close_position", self.close_position), web.post("/close_partial", self.close_position),
            web.route("*", "/{tail:.*}", self.unknown),
        ])
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", port).start()
        return f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
