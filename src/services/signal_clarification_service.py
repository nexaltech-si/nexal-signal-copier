"""
Signal Clarification Service

Vision-extracted signals (plans and direct entry/SL/TP setups alike)
sometimes have a clear direction, entry and target but no readable
instrument ticker on the chart — or the AI grabs unrelated text (e.g. a
quote-currency badge reading "USD" off a chart that's actually XAUUSD).
Instead of dropping (or worse, executing on a wrong guess), this service
holds the signal and asks the user for the correct symbol via Telegram
(button picker + /symbol command) or the dashboard, then resumes normal
processing — plan registration for plans, trading_service.process_signal
for direct signals.
"""
import base64
import json
import re
from typing import Optional, Tuple

from loguru import logger

from src.models.signal import TradingSignal
from src.models.enums import SignalAction, OrderType


class SignalClarificationService:

    async def request_clarification(self, signal: TradingSignal) -> dict:
        """Persist the plan awaiting a symbol and ask the user. Returns a summary dict."""
        from src.core.database_service import db_service
        from src.integrations.telegram.unified_sender import notification_sender
        from config.settings import settings

        signal_db_id = await self._save_pending(signal, db_service)

        primary = (signal.plan_data or {}).get("primary", {}) if signal.plan_data else {}
        direction = signal.order_type.value if signal.order_type else "?"
        entry = signal.entry_price if signal.entry_price is not None else primary.get("entry_min")
        take_profits = signal.take_profit or primary.get("take_profits") or []

        summary = {
            "id": signal_db_id,
            "field": signal.needs_clarification or "symbol",
            "order_type": direction,
            "entry": entry,
            "take_profit": take_profits,
            "is_plan": signal.is_plan,
        }

        if not signal_db_id:
            logger.error("Could not save pending clarification signal — dropping")
            return summary

        raw_symbols = getattr(
            settings, 'vision_allowed_symbols',
            "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,US30,NAS100,SPX500,"
            "GBPJPY,USDCAD,AUDUSD,NZDUSD,USDCHF,EURJPY,EURGBP",
        )
        fallback_symbols = [s.strip().upper() for s in str(raw_symbols).split(',') if s.strip()]

        # The price levels are the best clue we have about the instrument: ask
        # the broker which of its symbols actually trade in that range and offer
        # those, rather than a fixed list the setup may have nothing to do with.
        levels = self._price_levels(signal, entry, take_profits, primary)
        candidates = await self._candidates(levels)

        buttons = [
            {"symbol": c["symbol"], "label": f"{c['symbol']} · {self._fmt(c['price'])}"}
            for c in candidates
        ]
        # Top up with the configured favourites so there's always something to tap
        picked = {c["symbol"].upper() for c in candidates}
        for sym in fallback_symbols:
            if len(buttons) >= 12:
                break
            if sym.upper() not in picked:
                buttons.append({"symbol": sym, "label": sym})

        short_id = signal_db_id[:8]
        setup_kind = "plan" if signal.is_plan else "signal"
        if candidates:
            match_line = (
                "Instruments trading near those levels right now:\n"
                + "\n".join(
                    f"  • <b>{c['symbol']}</b> @ {self._fmt(c['price'])} "
                    f"({c['distance_pct']:.2f}% off entry)"
                    for c in candidates[:5]
                )
                + "\n\n"
            )
        else:
            match_line = ""

        text = (
            f"❓ <b>Which instrument is this?</b>\n\n"
            f"Found a {direction} {setup_kind} but couldn't read the symbol off the chart.\n"
            f"Entry: <code>{entry}</code>  SL: <code>{signal.stop_loss}</code>  "
            f"TP: <code>{take_profits}</code>\n\n"
            f"{match_line}"
            f"Tap one below, or reply <code>/symbol TICKER</code> "
            f"(or <code>/symbol {short_id} TICKER</code> if several are waiting)."
        )

        sent = False
        try:
            sent = bool(await notification_sender.send_symbol_picker(text, signal_db_id, buttons))
        except Exception as e:
            logger.warning(f"Could not send symbol clarification request: {e}")

        if not sent:
            # No button-capable sender — the /symbol command still works, so make
            # sure the request at least reaches the user as text.
            try:
                await notification_sender.send_message(text)
            except Exception as e:
                logger.warning(f"Could not send symbol clarification fallback text: {e}")

        logger.info(f"❓ Asked user for symbol on {setup_kind} {short_id}")
        summary["candidates"] = [c["symbol"] for c in candidates]
        return summary

    @staticmethod
    def _fmt(price: float) -> str:
        """Render a quote without trailing-zero noise (3350.4, 1.08345)."""
        try:
            return f"{float(price):.5f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(price)

    @staticmethod
    def _price_levels(signal, entry, take_profits, primary) -> list:
        """Entry first (it anchors the search), then SL and TPs as sanity checks."""
        levels = []
        for value in (entry, primary.get("entry_min"), primary.get("entry_max"), signal.stop_loss):
            if value is not None:
                levels.append(value)
        for tp in (take_profits or []):
            if isinstance(tp, dict):
                tp = tp.get("price")
            if tp is not None:
                levels.append(tp)
        out = []
        for level in levels:
            try:
                value = float(level)
            except (TypeError, ValueError):
                continue
            if value > 0:
                out.append(value)
        return out

    @staticmethod
    async def _candidates(levels: list) -> list:
        """Symbols whose live price brackets the signal's levels (best first)."""
        if not levels:
            return []
        try:
            from src.services.symbol_matcher_service import symbol_matcher_service

            return await symbol_matcher_service.find_by_price(levels, limit=8)
        except Exception as e:
            logger.warning(f"Symbol matching by price range failed: {e}")
            return []

    async def _save_pending(self, signal: TradingSignal, db_service) -> Optional[str]:
        """Persist the Signal with status=AWAITING_SYMBOL so it survives until resolved."""
        try:
            import hashlib
            msg_hash = hashlib.md5(
                f"{signal.channel_id}:{signal.message_id}".encode()
            , usedforsecurity=False).hexdigest()

            record = await db_service.db.signal.upsert(
                where={"channelId_messageId": {
                    "channelId": str(signal.channel_id or ""),
                    "messageId": signal.message_id or 0,
                }},
                data={
                    "create": {
                        "action": signal.action.value if signal.action else "OPEN",
                        "orderType": signal.order_type.value if signal.order_type else "BUY",
                        "symbol": "",
                        "entryPrice": signal.entry_price,
                        "stopLoss": signal.stop_loss,
                        "takeProfit": json.dumps(signal.take_profit or []),
                        "confidence": signal.confidence,
                        "channelId": str(signal.channel_id or ""),
                        "channelName": signal.channel_name,
                        "messageId": signal.message_id or 0,
                        "rawMessage": signal.raw_message or "",
                        "messageHash": msg_hash,
                        "imageData": (
                            base64.b64encode(signal.image_data).decode("utf-8")
                            if isinstance(signal.image_data, bytes) else signal.image_data
                        ),
                        "status": "AWAITING_SYMBOL",
                        "rejectionReason": "Vision could not determine a valid instrument symbol",
                        "isPlan": signal.is_plan,
                        "planData": json.dumps(signal.plan_data or {}),
                    },
                    "update": {
                        "status": "AWAITING_SYMBOL",
                        "rejectionReason": "Vision could not determine a valid instrument symbol",
                        "isPlan": signal.is_plan,
                        "planData": json.dumps(signal.plan_data or {}),
                    },
                },
            )
            return record.id
        except Exception as e:
            logger.error(f"Error saving pending clarification signal: {e}", exc_info=True)
            return None

    async def list_pending(self) -> list:
        """Signals still waiting on a symbol, newest first."""
        from src.core.database_service import db_service

        try:
            return await db_service.db.signal.find_many(
                where={"status": "AWAITING_SYMBOL"},
                order={"createdAt": "desc"},
            )
        except Exception as e:
            logger.error(f"Error looking up pending clarification signals: {e}")
            return []

    async def resolve(self, signal_id_or_prefix: Optional[str], symbol: str) -> Tuple[bool, str]:
        """
        User answered — fill in the symbol and resume processing.

        `signal_id_or_prefix` may be None or empty, in which case the newest
        pending request is used (the common case: one request outstanding, user
        just replies `/symbol XAUUSD`).
        """
        from src.services.plan_filter_service import plan_filter_service
        from src.core.database_service import db_service

        typed = (symbol or "").strip()
        # Broker tickers aren't always alphanumeric — XAUUSD.m, US30.cash, GER40+
        if len(typed) < 2 or not re.fullmatch(r"[A-Za-z0-9._\-+#/]{2,20}", typed):
            safe = typed.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:32]
            return False, f"'{safe}' doesn't look like a ticker (e.g. XAUUSD or XAUUSD.m)."

        candidates = await self.list_pending()
        if not candidates:
            return False, "Nothing is waiting on a symbol right now."

        prefix = (signal_id_or_prefix or "").strip()
        if prefix:
            record = next(
                (r for r in candidates if r.id.startswith(prefix) or r.id.endswith(prefix)),
                None,
            )
            if not record:
                return False, (
                    f"No pending symbol request matching '{prefix[:8]}' — "
                    "it may have already been answered. Send /symbol to see what's waiting."
                )
        elif len(candidates) == 1:
            record = candidates[0]
        else:
            listing = "\n".join(
                f"  • <code>{r.id[:8]}</code> {r.orderType} entry {r.entryPrice}"
                for r in candidates[:5]
            )
            return False, (
                f"{len(candidates)} requests are waiting — say which one:\n{listing}\n\n"
                f"e.g. <code>/symbol {candidates[0].id[:8]} {typed.upper()}</code>"
            )

        # Map whatever they typed onto a symbol the broker actually quotes, so a
        # trade doesn't fail later on a ticker that doesn't exist here.
        symbol = typed.upper()
        try:
            from src.services.symbol_matcher_service import symbol_matcher_service

            broker_symbol, suggestions = await symbol_matcher_service.resolve_user_symbol(typed)
            if broker_symbol:
                symbol = broker_symbol
            elif suggestions:
                return False, (
                    f"Your broker doesn't list '{typed.upper()}'. Did you mean: "
                    + ", ".join(f"<code>{s}</code>" for s in suggestions[:6])
                    + "?"
                )
            else:
                return False, (
                    f"Your broker doesn't list '{typed.upper()}' — check the exact "
                    "name in Market Watch and try again."
                )
        except Exception as e:
            logger.warning(f"Could not verify '{typed}' against the broker: {e}")

        try:
            plan_data = json.loads(record.planData) if record.planData else {}
            take_profit = json.loads(record.takeProfit) if record.takeProfit else []

            signal = TradingSignal(
                symbol=symbol,
                action=SignalAction.OPEN,
                order_type=OrderType.BUY if record.orderType == "BUY" else OrderType.SELL,
                entry_price=record.entryPrice,
                stop_loss=record.stopLoss,
                take_profit=take_profit,
                raw_message=record.rawMessage,
                confidence=record.confidence,
                channel_id=record.channelId,
                channel_name=record.channelName,
                message_id=record.messageId,
                is_plan=bool(record.isPlan),
                plan_data=plan_data,
            )
            if record.imageData:
                try:
                    signal.image_data = base64.b64decode(record.imageData)
                except Exception as _exc:
                    logger.debug(f"Suppressed exception: {_exc!r}")
        except Exception as e:
            logger.error(f"Error reconstructing signal {record.id}: {e}", exc_info=True)
            return False, "Couldn't rebuild that signal — check the logs."

        await db_service.db.signal.update(
            where={"id": record.id},
            data={"symbol": symbol, "status": "VALIDATED", "rejectionReason": None},
        )

        if signal.is_plan:
            await plan_filter_service.validate_and_register(signal)
            logger.info(f"✅ Symbol resolved for {record.id[:8]}: {symbol}")
            return True, f"Got it — registering {symbol} {record.orderType} plan now."
        else:
            from src.services.trading_service import trading_service
            try:
                await trading_service.process_signal(signal)
            except Exception as e:
                logger.error(f"Error processing resolved signal {record.id}: {e}", exc_info=True)
                return False, f"Symbol saved but trade processing failed: {e}"
            logger.info(f"✅ Symbol resolved for {record.id[:8]}: {symbol}")
            return True, f"Got it — processing {symbol} {record.orderType} now."


signal_clarification_service = SignalClarificationService()
