import math as _math
from telethon import TelegramClient
from telethon.errors import RPCError
from loguru import logger
from datetime import datetime

from config import settings
from src.models import TradingSignal, TradeResult, RiskAssessment

# Shared HTML escaping — single definition lives in src/utils/telegram_format.py
from src.utils.telegram_format import escape_html


def _fmt_price(val, decimals=2):
    """Format a price value safely, returning '—' for None."""
    if val is None:
        return "—"
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_tp(take_profit):
    """Format take-profit (single float, list, or None) into a display string."""
    if not take_profit:
        return "—"
    if isinstance(take_profit, list):
        return "  |  ".join(_fmt_price(tp) for tp in take_profit if tp is not None) or "—"
    return _fmt_price(take_profit)


def _fmt_pips(val):
    """Format a pip value with sign and one decimal."""
    if val is None:
        return ""
    try:
        v = float(val)
        return f"{v:+.1f} pips"
    except (TypeError, ValueError):
        return ""


def _direction_emoji(order_type) -> str:
    """Return emoji for trade direction."""
    if order_type is None:
        return "📊"
    ot = order_type.value if hasattr(order_type, 'value') else str(order_type)
    return "🟢" if ot.upper() == "BUY" else "🔴"


class NotificationSender:
    """
    Send notifications to Telegram using Telethon.
    """

    def __init__(self):
        self.client = None
        self.notification_chat_id = settings.telegram_notification_chat_id

    @staticmethod
    def _get_signal_type_str(signal_type) -> str:
        if signal_type is None:
            return "UNKNOWN"
        return signal_type if isinstance(signal_type, str) else signal_type.value

    async def initialize(self, client: TelegramClient = None):
        try:
            if client:
                self.client = client
                logger.info("   Using shared Telethon client")
            else:
                self.client = TelegramClient(
                    settings.telegram_session_name + "_notifier",
                    settings.telegram_api_id,
                    settings.telegram_api_hash
                )
                await self.client.start(phone=settings.telegram_phone)
                logger.info("   Created separate Telethon client")

            me = await self.client.get_me()
            logger.success(f"✅ Notification sender initialized: {me.first_name}")

            if not self.notification_chat_id:
                logger.warning("⚠️  TELEGRAM_NOTIFICATION_CHAT_ID not set in .env")
                logger.warning("   Notifications will be disabled.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize notification sender: {str(e)}")
            raise

    async def send_message(self, message: str, parse_mode: str = "html", force_send: bool = False):
        if not self.client:
            return False
        if not self.notification_chat_id:
            return False

        try:
            if not self.client.is_connected():
                if force_send:
                    try:
                        await self.client.connect()
                    except Exception:
                        return False
                else:
                    return False

            chat_id = self.notification_chat_id
            if chat_id and chat_id.lstrip('-').isdigit():
                chat_id = int(chat_id)

            await self.client.send_message(chat_id, message, parse_mode=parse_mode)
            logger.debug("📤 Notification sent")
            return True

        except RPCError as e:
            err = str(e).lower()
            if 'disconnected' in err or 'connection' in err:
                logger.warning(f"⚠️ Notification skipped (connection): {e}")
            else:
                logger.error(f"❌ Failed to send notification: {e}")
            return False
        except Exception as e:
            err = str(e).lower()
            if 'disconnected' in err or 'connection' in err:
                logger.warning(f"⚠️ Notification skipped (connection): {e}")
            else:
                logger.error(f"❌ Failed to send notification: {e}")
            return False

    # ── helpers ────────────────────────────────────────────────────────────────

    def _channel_label(self, signal: TradingSignal) -> str:
        ch = getattr(signal, 'channel_name', None) or getattr(signal, 'channel_id', None)
        return escape_html(str(ch)) if ch else "Unknown"

    def _entry_display(self, signal: TradingSignal) -> str:
        has_range = (
            getattr(signal, 'entry_range_min', None)
            and getattr(signal, 'entry_range_max', None)
        )
        if has_range:
            return f"{signal.entry_range_max} – {signal.entry_range_min}"
        return _fmt_price(signal.entry_price) if signal.entry_price else "Market"

    def _direction_str(self, signal: TradingSignal) -> str:
        ot = getattr(signal, 'order_type', None)
        if ot is None:
            return ""
        return ot.value if hasattr(ot, 'value') else str(ot)

    def _signal_header(self, signal: TradingSignal) -> str:
        """DRY: direction emoji + BUY/SELL + SYMBOL + channel line."""
        direction = self._direction_str(signal)
        emoji = _direction_emoji(getattr(signal, 'order_type', None))
        ch = self._channel_label(signal)
        return (
            f"{emoji} <b>{direction} {escape_html(signal.symbol or '?')}</b>\n"
            f"📡 from {ch}\n"
        )

    # ── notifications ──────────────────────────────────────────────────────────

    async def notify_signal_received(self, signal: TradingSignal):
        header = self._signal_header(signal)
        entry = self._entry_display(signal)
        sl = _fmt_price(signal.stop_loss)
        tp = _fmt_tp(signal.take_profit)

        message = (
            f"🆕 <b>New Signal</b>\n\n"
            f"{header}\n"
            f"💰 <b>Entry:</b>  <code>{entry}</code>\n"
            f"🛑 <b>SL:</b>     <code>{sl}</code>\n"
            f"🎯 <b>TP:</b>     <code>{tp}</code>\n"
            f"📈 <b>Confidence:</b> {signal.confidence:.0%}\n\n"
            f"<i>Processing…</i>"
        )
        return await self.send_message(message)

    async def notify_signal_rejected(self, signal: TradingSignal, reason: str):
        header = self._signal_header(signal)
        # Skip header if we barely know anything about the signal
        if not signal.symbol or not getattr(signal, 'order_type', None):
            header = ""

        message = (
            f"🚫 <b>Signal Rejected</b>\n\n"
            f"{header}"
            f"❌ <b>Reason:</b> {escape_html(reason)}\n\n"
            f"<i>Rejected by risk management — no trade placed.</i>"
        )
        return await self.send_message(message)

    async def notify_trade_executed(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        trade_result: TradeResult
    ):
        header = self._signal_header(signal)
        entry = (
            _fmt_price(trade_result.entry_price)
            if trade_result.entry_price
            else self._entry_display(signal)
        )
        sl = _fmt_price(signal.stop_loss)
        tp = _fmt_tp(signal.take_profit)
        sl_pips = _fmt_pips(risk_assessment.stop_loss_pips)
        tp_pips = _fmt_pips(risk_assessment.take_profit_pips)
        pos_id = escape_html(str(trade_result.position_id)) if trade_result.position_id else "—"
        order_id = escape_html(str(trade_result.order_id)) if trade_result.order_id else "—"

        message = (
            f"✅ <b>Trade Executed</b>\n\n"
            f"{header}\n"
            f"💰 <b>Entry:</b>  <code>{entry}</code>\n"
            f"📦 <b>Size:</b>   <code>{risk_assessment.calculated_lot_size} lots</code>\n"
            f"🛑 <b>SL:</b>     <code>{sl}</code>  {sl_pips}\n"
            f"🎯 <b>TP:</b>     <code>{tp}</code>  {tp_pips}\n"
            f"⚠️  <b>Risk:</b>   ${risk_assessment.risk_amount:.2f} "
            f"({risk_assessment.risk_percent:.2f}%)  |  "
            f"R:R 1:{risk_assessment.risk_reward_ratio:.1f}\n\n"
            f"🆔 <b>Position:</b> <code>{pos_id}</code>\n"
            f"📝 <b>Order:</b>    <code>{order_id}</code>\n"
            f"⏰ <b>Time:</b>     {trade_result.timestamp.strftime('%H:%M:%S')}\n\n"
            f"<i>Trade is live — good luck!</i>"
        )
        return await self.send_message(message)

    async def notify_trade_failed(self, signal: TradingSignal, error: str):
        header = self._signal_header(signal) if signal.symbol else ""

        message = (
            f"❌ <b>Trade Failed</b>\n\n"
            f"{header}"
            f"⚠️ <b>Error:</b> {escape_html(error)}\n\n"
            f"<i>Check logs for details.</i>"
        )
        return await self.send_message(message)

    async def notify_position_closed(
        self,
        signal: TradingSignal,
        close_price: float,
        profit_loss: float,
        profit_loss_pips: float
    ):
        is_profit = profit_loss > 0
        emoji = "🟢" if is_profit else "🔴"
        label = "WIN" if is_profit else "LOSS"
        pl_sign = "+" if is_profit else ""
        pips_sign = "+" if profit_loss_pips > 0 else ""

        message = (
            f"{emoji} <b>Position Closed — {label}</b>\n\n"
            f"📊 <b>{escape_html(signal.symbol or '?')}</b>\n\n"
            f"💵 <b>Close:</b>  <code>{close_price:.2f}</code>\n"
            f"📥 <b>Entry:</b>  <code>{signal.entry_price:.2f}</code>\n"
            f"💰 <b>P/L:</b>    <code>{pl_sign}${profit_loss:.2f}</code>"
            f"  ({pips_sign}{profit_loss_pips:.1f} pips)\n\n"
            f"⏰ <b>Closed:</b>  {datetime.now().strftime('%H:%M:%S')}"
        )
        return await self.send_message(message)

    async def notify_daily_summary(self, stats: dict):
        message = (
            f"📊 <b>Daily Summary</b>\n\n"
            f"📈 <b>Signals:</b>  {stats.get('total_signals', 0)} total  |  "
            f"{stats.get('executed', 0)} executed  |  "
            f"{stats.get('rejected', 0)} rejected\n\n"
            f"💰 <b>P/L:</b>      <code>${stats.get('total_pl', 0):+.2f}</code>\n"
            f"🎯 <b>Win Rate:</b>  {stats.get('win_rate', 0):.1f}%\n"
            f"📊 <b>Best:</b>     <code>${stats.get('best_trade', 0):+.2f}</code>  |  "
            f"<b>Worst:</b> <code>${stats.get('worst_trade', 0):+.2f}</code>\n\n"
            f"💵 <b>Balance:</b>  <code>${stats.get('start_balance', 0):.2f}</code> → "
            f"<code>${stats.get('current_balance', 0):.2f}</code>"
            f"  ({stats.get('daily_change_percent', 0):+.2f}%)\n\n"
            f"<i>End of day</i>"
        )
        return await self.send_message(message)

    async def notify_error(self, error_type: str, error_message: str):
        message = (
            f"🚨 <b>Error</b>\n\n"
            f"<b>Type:</b> {escape_html(error_type)}\n"
            f"<b>Detail:</b> {escape_html(error_message)}\n\n"
            f"<i>Check logs for full traceback.</i>"
        )
        return await self.send_message(message)

    async def notify_bot_started(self):
        message = (
            f"🟢 <b>Bot Started</b>\n\n"
            f"✅ All systems operational\n"
            f"🔊 Monitoring channels for signals\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return await self.send_message(message)

    async def notify_bot_stopped(self):
        message = (
            f"🔴 <b>Bot Stopped</b>\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return await self.send_message(message, force_send=True)

    async def notify_risk_warning(self, warning: str):
        message = (
            f"⚠️ <b>Risk Warning</b>\n\n"
            f"{escape_html(warning)}\n\n"
            f"<i>Review risk parameters.</i>"
        )
        return await self.send_message(message)

    async def notify_approval_request(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        signal_id: str,
        timeout_seconds: int
    ):
        header = self._signal_header(signal)
        entry = self._entry_display(signal)
        sl = _fmt_price(signal.stop_loss)
        tp = _fmt_tp(signal.take_profit)
        timeout_min = _math.ceil(timeout_seconds / 60)

        # Determine order type label
        st = getattr(signal, 'signal_type', None)
        st_val = st.value if hasattr(st, 'value') else str(st or "")
        if "LIMIT" in st_val.upper():
            order_label = "LIMIT"
        elif "STOP" in st_val.upper():
            order_label = "STOP"
        else:
            order_label = "MARKET"

        # High-risk override banner — trade breaches the configured risk limit.
        high_risk_banner = ""
        if getattr(risk_assessment, 'risk_limit_exceeded', False):
            max_risk = getattr(settings, 'max_risk_per_trade_percent', 0)
            high_risk_banner = (
                f"🚨🚨🚨 <b>HIGH-RISK TRADE</b> 🚨🚨🚨\n"
                f"⚠️ Risks <b>{risk_assessment.risk_percent:.2f}%</b> "
                f"(<b>${risk_assessment.risk_amount:,.2f}</b>) — above your max of "
                f"<b>{max_risk}%</b>.\n"
                f"⚠️ Lot is already at minimum. Approve only if you accept the extra risk.\n\n"
            )

        message = (
            f"{high_risk_banner}"
            f"⏳ <b>Approval Required</b>\n\n"
            f"{header}\n"
            f"📋 <b>Type:</b>   {order_label} ORDER\n"
            f"💰 <b>Entry:</b>  <code>{entry}</code>\n"
            f"🛑 <b>SL:</b>     <code>{sl}</code>\n"
            f"🎯 <b>TP:</b>     <code>{tp}</code>\n"
            f"📦 <b>Size:</b>   <code>{risk_assessment.calculated_lot_size} lots</code>\n"
            f"⚠️  <b>Risk:</b>   {risk_assessment.risk_percent:.1f}%  |  "
            f"R:R 1:{risk_assessment.risk_reward_ratio:.1f}\n\n"
            f"🆔 <code>{escape_html(signal_id[:16])}</code>"
            f"  ·  expires in {timeout_min} min\n\n"
            f"<b>Reply:</b>\n"
            f"<code>/execute {signal_id[:8]}</code>  to approve\n"
            f"<code>/reject {signal_id[:8]}</code>   to reject\n"
            f"<code>/pending</code>                  to list all"
        )

        approval_channel = getattr(settings, 'approval_channel_id', None) or self.notification_chat_id
        if not approval_channel:
            logger.error("❌ No approval channel configured")
            return False

        try:
            await self.client.send_message(approval_channel, message, parse_mode='html')
            logger.debug(f"✅ Approval request sent via Telethon to {approval_channel}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send approval request via Telethon: {e}")
            return False

    async def notify_approval_confirmed(self, signal: TradingSignal, risk_assessment: RiskAssessment):
        header = self._signal_header(signal)

        message = (
            f"✅ <b>Approved — Executing</b>\n\n"
            f"{header}\n"
            f"📦 <b>Size:</b> <code>{risk_assessment.calculated_lot_size} lots</code>\n\n"
            f"<i>Trade is being placed…</i>"
        )
        return await self.send_message(message)

    async def notify_approval_timeout(self, signal: TradingSignal, risk_assessment: RiskAssessment):
        header = self._signal_header(signal) if signal.symbol else ""

        message = (
            f"⏰ <b>Approval Expired</b>\n\n"
            f"{header}"
            f"<i>Signal timed out without approval.</i>"
        )
        return await self.send_message(message)


# Singleton instance
notification_sender = NotificationSender()
