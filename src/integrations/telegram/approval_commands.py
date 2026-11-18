"""
Telegram Bot Command Handler for Trade Approval
Handles /execute, /reject, /pending, /status, /positions, /balance, /help,
/pause, /resume commands and inline button callbacks.
"""
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from loguru import logger

from config import settings
from src.services.approval_queue import approval_queue, brain_action_queue
from src.services.trading_service import trading_service
from src.integrations.telegram.unified_sender import notification_sender
from src.core.database_service import db_service


# ─────────────────────────────────────────────────────────────────────────────
# Auth helper
# ─────────────────────────────────────────────────────────────────────────────

async def _is_authorized(chat_id: str, user_id: Optional[int] = None) -> bool:
    """
    Returns True if the sender is allowed to use bot commands.

    Rules (in order):
    1. Anonymous post in the configured approval channel → authorized.
       Channel posts carry no from_user, so a user allowlist can never match
       and every command sent there would be rejected. Only channel admins can
       post, and the channel itself is the gate.
    2. If BOT_ALLOWED_USER_IDS is non-empty, check the sender is in the list.
       If they are → authorized regardless of which chat they sent from.
       If they aren't → deny.
    3. No allowlist configured: fall back to channel gate.
       If an approval channel is set, message must come from it.
    4. No allowlist and no channel gate → allow everyone.
    """
    import json as _json

    approval_channel = getattr(settings, 'approval_channel_id', None)

    # 1. Anonymous channel post in the approval channel
    if user_id is None and approval_channel and chat_id == str(approval_channel):
        return True

    # 2. Explicit user allowlist — wins over channel gate
    try:
        from src.services.settings_service import settings_service
        raw = await settings_service.get_setting("BOT_ALLOWED_USER_IDS", [])
        if isinstance(raw, str):
            allowed = _json.loads(raw)
        else:
            allowed = list(raw) if raw else []
        if allowed:
            return str(user_id) in [str(uid) for uid in allowed]
    except Exception as _exc:
        logger.debug(f"Suppressed exception: {_exc!r}")

    # 3. Channel gate (only applies when no allowlist is configured)
    if approval_channel and chat_id != str(approval_channel):
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# /execute
# ─────────────────────────────────────────────────────────────────────────────

async def execute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /execute <signal_id> — approve a pending signal"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /execute <signal_id>\n"
            "Not sure which ID? Run /pending and I'll show you what's waiting."
        )
        return

    signal_id_prefix = context.args[0]
    matching = next(
        (p for p in approval_queue.get_all_pending() if p.signal_id.startswith(signal_id_prefix)),
        None
    )

    if not matching:
        await update.message.reply_text(
            f"Couldn't find a signal starting with '{signal_id_prefix}'. "
            "Run /pending to see what's in the queue."
        )
        return

    if not approval_queue.approve_signal(matching.signal_id):
        await update.message.reply_text("Something went wrong approving that signal — it may have already expired.")
        return

    await db_service.update_signal_status(matching.signal_id, "PROCESSING")
    logger.info(f"✅ Signal {matching.signal_id[:8]}... approved via /execute command")

    channel_name = getattr(matching.signal, 'channel_name', None) or getattr(matching.signal, 'channel_id', None)
    channel_str = str(channel_name) if channel_name else "Unknown"
    order_type = getattr(matching.signal, 'order_type', None)
    direction_str = order_type.value if hasattr(order_type, 'value') else (str(order_type) if order_type else "N/A")

    await update.message.reply_text(
        f"Got it — placing <b>{direction_str} {matching.signal.symbol}</b> now.\n"
        f"Source: {channel_str}",
        parse_mode='HTML'
    )

    try:
        await trading_service.execute_after_approval(
            matching.signal, matching.risk_assessment, matching.signal_id
        )
    except Exception as e:
        logger.error(f"Failed to execute approved trade: {e}")
        await update.message.reply_text(f"Trade failed to execute: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /reject
# ─────────────────────────────────────────────────────────────────────────────

async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reject <signal_id> — reject a pending signal"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /reject <signal_id>\n"
            "Run /pending to see the IDs of signals waiting for review."
        )
        return

    signal_id_prefix = context.args[0]
    matching = next(
        (p for p in approval_queue.get_all_pending() if p.signal_id.startswith(signal_id_prefix)),
        None
    )

    if not matching:
        await update.message.reply_text(
            f"No signal matching '{signal_id_prefix}' found. "
            "It may have already timed out."
        )
        return

    rejected = approval_queue.reject_signal(matching.signal_id, "Rejected via /reject command")
    if not rejected:
        await update.message.reply_text("Couldn't reject that signal — may have already been processed.")
        return

    logger.info(f"❌ Signal {matching.signal_id[:8]}... rejected via /reject command")

    order_type = getattr(matching.signal, 'order_type', None)
    direction_str = order_type.value if hasattr(order_type, 'value') else (str(order_type) if order_type else "N/A")

    await update.message.reply_text(
        f"Skipped — <b>{direction_str} {matching.signal.symbol}</b> won't be placed.",
        parse_mode='HTML'
    )


# ─────────────────────────────────────────────────────────────────────────────
# /symbol — answer a "which instrument is this?" clarification request
# ─────────────────────────────────────────────────────────────────────────────

def _looks_like_signal_id(token: str) -> bool:
    """Signal ids are long lowercase cuid-ish strings; tickers are short."""
    token = (token or "").strip()
    return len(token) >= 8 and token.lower() == token and token.isalnum()


async def symbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /symbol — answer a pending "which instrument is this?" request.

    Accepted forms:
        /symbol                    → list what's waiting
        /symbol XAUUSD             → answer the only (or newest) pending request
        /symbol a1b2c3d4 XAUUSD    → answer a specific one
        /symbol XAUUSD a1b2c3d4    → same, either order
    """
    # Posts in a channel arrive as channel_post, not message — effective_message
    # covers both, otherwise the command silently does nothing there.
    message = update.effective_message
    if not message:
        return

    chat_id = str(message.chat_id)
    user = update.effective_user
    user_id = user.id if user else None
    if not await _is_authorized(chat_id, user_id):
        await message.reply_text("You're not authorized to use this command.")
        return

    from src.services.signal_clarification_service import signal_clarification_service

    args = [a for a in (context.args or []) if a.strip()]

    if not args:
        pending = await signal_clarification_service.list_pending()
        if not pending:
            await message.reply_text("Nothing is waiting on a symbol right now.")
            return
        listing = "\n".join(
            f"  • <code>{r.id[:8]}</code> — {r.orderType} entry {r.entryPrice} "
            f"SL {r.stopLoss}"
            for r in pending[:10]
        )
        await message.reply_text(
            f"<b>Waiting on a symbol ({len(pending)})</b>\n{listing}\n\n"
            f"Reply <code>/symbol {pending[0].id[:8]} XAUUSD</code> "
            f"(or just <code>/symbol XAUUSD</code> if only one is waiting).",
            parse_mode='HTML',
        )
        return

    signal_id_prefix, symbol = None, None
    if len(args) == 1:
        symbol = args[0]
    else:
        first, second = args[0], args[1]
        if _looks_like_signal_id(first):
            signal_id_prefix, symbol = first, second
        elif _looks_like_signal_id(second):
            signal_id_prefix, symbol = second, first
        else:
            signal_id_prefix, symbol = first, second

    # Answering by replying to the picker message pins it to that request
    if not signal_id_prefix:
        replied = getattr(message, 'reply_to_message', None)
        source = (getattr(replied, 'text', None) or getattr(replied, 'caption', None)) if replied else None
        if source:
            import re as _re
            match = _re.search(r"/symbol\s+([a-z0-9]{8})\s", source)
            if match:
                signal_id_prefix = match.group(1)

    ok, reply = await signal_clarification_service.resolve(signal_id_prefix, symbol)
    await message.reply_text(reply, parse_mode='HTML')


# ─────────────────────────────────────────────────────────────────────────────
# /pending
# ─────────────────────────────────────────────────────────────────────────────

def _build_pending_list_message(pending_signals) -> tuple[str, InlineKeyboardMarkup]:
    """Build the pending signals message and keyboard."""
    message = f"<b>Waiting for approval ({len(pending_signals)})</b>\n\n"
    keyboard = []

    for i, pending in enumerate(pending_signals, 1):
        signal = pending.signal
        order_type = getattr(signal, 'order_type', None)
        direction_str = order_type.value if hasattr(order_type, 'value') else (str(order_type) if order_type else "N/A")
        signal_type = getattr(signal, 'signal_type', None)
        signal_type_val = signal_type.value if hasattr(signal_type, 'value') else (str(signal_type) if signal_type else "")
        if "LIMIT" in signal_type_val.upper():
            order_type_label = "LIMIT"
        elif "STOP" in signal_type_val.upper():
            order_type_label = "STOP"
        else:
            order_type_label = "MARKET"

        channel_name = getattr(signal, 'channel_name', None) or getattr(signal, 'channel_id', None)
        channel_str = str(channel_name) if channel_name else "Unknown"
        remaining_sec = pending.get_remaining_seconds()
        remaining_min = remaining_sec // 60

        message += (
            f"<b>{i}. {direction_str} {signal.symbol} — {order_type_label}</b>\n"
            f"   Entry: {signal.entry_price or 'Market'}\n"
            f"   Source: {channel_str}\n"
            f"   ID: <code>{pending.signal_id[:8]}</code>  ⏰ {remaining_min}m {remaining_sec % 60}s left\n\n"
        )
        keyboard.append([
            InlineKeyboardButton(f"✅ Take {i}", callback_data=f"approve:{pending.signal_id}"),
            InlineKeyboardButton(f"❌ Skip {i}", callback_data=f"reject:{pending.signal_id}")
        ])

    return message, InlineKeyboardMarkup(keyboard)


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pending — list all pending signals"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    pending_signals = approval_queue.get_all_pending()

    if not pending_signals:
        await update.message.reply_text("Nothing waiting right now — the queue is clear.")
        return

    message, reply_markup = _build_pending_list_message(pending_signals)
    await update.message.reply_text(message, parse_mode='HTML', reply_markup=reply_markup)


# ─────────────────────────────────────────────────────────────────────────────
# /status
# ─────────────────────────────────────────────────────────────────────────────

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status — bot health and quick summary"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    # Open positions count
    try:
        open_trades = await db_service.get_open_positions()
        open_count = len(open_trades)
    except Exception:
        open_trades = []
        open_count = 0

    # Today's P&L from closed trades
    try:
        from datetime import datetime, timezone
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        closed_today = await db_service.db.trade.find_many(
            where={
                "status": "CLOSED",
                "closedAt": {"gte": today_start}
            }
        )
        today_pnl = sum(t.profitLoss or 0.0 for t in closed_today)
        today_trades = len(closed_today)
    except Exception:
        today_pnl = 0.0
        today_trades = 0

    pending_count = len(approval_queue.get_all_pending())
    paused_str = "⏸️ <b>Signal processing is paused.</b> Use /resume to turn it back on.\n\n" if approval_queue.paused else ""

    pnl_emoji = "📈" if today_pnl >= 0 else "📉"
    pnl_sign = "+" if today_pnl >= 0 else ""

    msg = (
        f"{paused_str}"
        f"<b>Bot Status</b>\n\n"
        f"🟢 Running\n"
        f"📊 Open positions: {open_count}\n"
        f"⏳ Waiting for approval: {pending_count}\n"
        f"{pnl_emoji} Today's P&L: {pnl_sign}${today_pnl:.2f} ({today_trades} trade{'s' if today_trades != 1 else ''} closed)"
    )
    await update.message.reply_text(msg, parse_mode='HTML')


# ─────────────────────────────────────────────────────────────────────────────
# /positions
# ─────────────────────────────────────────────────────────────────────────────

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /positions — list all open positions"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    try:
        open_trades = await db_service.get_open_positions()
    except Exception as e:
        await update.message.reply_text(f"Couldn't pull positions right now: {e}")
        return

    if not open_trades:
        await update.message.reply_text("No open positions at the moment.")
        return

    lines = [f"<b>Open positions ({len(open_trades)})</b>\n"]
    for t in open_trades:
        # db get_open_positions returns snake_case keys
        symbol = t.get('symbol') or '?'
        direction = str(t.get('order_type') or t.get('action') or '').upper()
        entry = t.get('entry_price')
        sl = t.get('stop_loss')
        # take_profit is stored as a list; show first target
        tp_raw = t.get('take_profit')
        tp = tp_raw[0] if isinstance(tp_raw, list) and tp_raw else (tp_raw if not isinstance(tp_raw, list) else None)

        def _fmt_price(v):
            if v is None:
                return "—"
            try:
                return f"{float(v):.5f}".rstrip('0').rstrip('.')
            except (TypeError, ValueError):
                return str(v)

        lines.append(
            f"<b>{direction} {symbol}</b>\n"
            f"  Entry: <code>{_fmt_price(entry)}</code>  SL: <code>{_fmt_price(sl)}</code>  TP: <code>{_fmt_price(tp)}</code>\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode='HTML')


# ─────────────────────────────────────────────────────────────────────────────
# /balance
# ─────────────────────────────────────────────────────────────────────────────

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance — show account balance and equity"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    try:
        account_info = await trading_service.get_account_info()
        if not account_info:
            await update.message.reply_text("Couldn't reach the account right now. Try again in a moment.")
            return

        balance = getattr(account_info, 'balance', None)
        equity = getattr(account_info, 'equity', None)
        margin = getattr(account_info, 'margin', None)
        free_margin = getattr(account_info, 'free_margin', None) or getattr(account_info, 'freeMargin', None)
        currency = getattr(account_info, 'currency', 'USD')

        balance_str = f"${balance:,.2f}" if balance is not None else "—"
        equity_str = f"${equity:,.2f}" if equity is not None else "—"
        margin_str = f"${margin:,.2f}" if margin is not None else "—"
        free_margin_str = f"${free_margin:,.2f}" if free_margin is not None else "—"

        msg = (
            f"<b>Account — {currency}</b>\n\n"
            f"💰 Balance: <code>{balance_str}</code>\n"
            f"📊 Equity: <code>{equity_str}</code>\n"
            f"📌 Used margin: <code>{margin_str}</code>\n"
            f"🟢 Free margin: <code>{free_margin_str}</code>"
        )
        await update.message.reply_text(msg, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"Couldn't load account info: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help — show available commands"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    msg = (
        "<b>What I can do</b>\n\n"
        "I watch your signal channels and manage trades on your account. "
        "Here's how to work with me:\n\n"
        "<b>Approvals</b>\n"
        "/pending — see what's waiting for your green light\n"
        "/execute &lt;id&gt; — place a trade from the queue\n"
        "/reject &lt;id&gt; — skip a trade from the queue\n\n"
        "<b>Account</b>\n"
        "/status — quick overview: open trades, today's P&L\n"
        "/positions — all open positions with entry, SL, TP\n"
        "/balance — account balance, equity, and margin\n\n"
        "<b>Control</b>\n"
        "/pause — stop processing new signals (open positions still managed)\n"
        "/resume — turn signal processing back on\n\n"
        "<b>Clarifications</b>\n"
        "/symbol — list setups waiting on an instrument\n"
        "/symbol &lt;TICKER&gt; — answer the one that's waiting (e.g. /symbol XAUUSD)\n"
        "/symbol &lt;id&gt; &lt;TICKER&gt; — answer a specific one when several are open\n"
        "(or just tap a button on the message — those are the instruments actually "
        "trading near the setup's price)\n\n"
        "<b>Tip</b>\n"
        "You can also tap the ✅/❌ buttons on approval messages directly — "
        "no need to type a command."
    )
    await update.message.reply_text(msg, parse_mode='HTML')


# ─────────────────────────────────────────────────────────────────────────────
# /pause / /resume
# ─────────────────────────────────────────────────────────────────────────────

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pause — stop processing new signals"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    if approval_queue.paused:
        await update.message.reply_text("Already paused — use /resume when you're ready to go again.")
        return

    approval_queue.paused = True
    logger.info("⏸️ Signal processing paused by user")
    await update.message.reply_text(
        "⏸️ Paused. I won't act on new signals until you say /resume.\n"
        "Any positions already open are still being managed."
    )


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume — resume signal processing"""
    if not update.message:
        return

    chat_id = str(update.message.chat_id)
    user_id = update.message.from_user.id if update.message.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await update.message.reply_text("You're not authorized to use this command.")
        return

    if not approval_queue.paused:
        await update.message.reply_text("Already running — nothing to resume.")
        return

    approval_queue.paused = False
    logger.info("▶️ Signal processing resumed by user")
    await update.message.reply_text("▶️ Back on. Watching for signals again.")


# ─────────────────────────────────────────────────────────────────────────────
# Inline button callback
# ─────────────────────────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks for approve/reject"""
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    user_id = query.from_user.id if query.from_user else None
    if not await _is_authorized(chat_id, user_id):
        await query.edit_message_text("You're not authorized to use this.")
        return

    callback_data = query.data

    # ── Show pending list ──────────────────────────────────────────────────
    if callback_data == "pending":
        pending_signals = approval_queue.get_all_pending()
        if not pending_signals:
            await query.edit_message_text("Nothing waiting right now — the queue is clear.")
            return
        message, reply_markup = _build_pending_list_message(pending_signals)
        await query.edit_message_text(message, parse_mode='HTML', reply_markup=reply_markup)
        return

    # ── Missed-while-offline command: apply / skip ─────────────────────────
    if callback_data.startswith("catchup:"):
        parts = callback_data.split(":", 2)
        if len(parts) != 3:
            await query.edit_message_text("Couldn't read that action.")
            return
        _, decision, item_id = parts
        from src.services.catchup_service import catchup_service
        if decision == "apply":
            await query.edit_message_text("On it — applying the missed command now...")
            ok, message = await catchup_service.apply(item_id)
            await query.message.reply_text(("✅ " if ok else "⚠️ ") + message, parse_mode='HTML')
        else:
            catchup_service.skip(item_id)
            await query.edit_message_text("Skipped — that missed command won't be applied.")
        return

    # ── Brain action approve/reject ────────────────────────────────────────
    if callback_data.startswith("brain_action:"):
        parts = callback_data.split(":", 2)
        if len(parts) != 3:
            await query.edit_message_text("Something went wrong — couldn't read that brain action.")
            return
        _, brain_action, action_id = parts
        pending = brain_action_queue.get(action_id)
        if not pending:
            await query.edit_message_text(
                "This brain action is no longer available — it may have already been handled or timed out."
            )
            return
        if brain_action == "approve":
            await query.edit_message_text(
                f"On it — running <b>{pending.action}</b> on {pending.symbol} now...",
                parse_mode='HTML'
            )
            success = await brain_action_queue.execute(action_id)
            if not success:
                await query.message.reply_text(
                    f"The action on {pending.symbol} didn't go through — check the logs for details."
                )
        elif brain_action == "reject":
            brain_action_queue.reject(action_id)
            await query.edit_message_text(
                f"Skipped — <b>{pending.action}</b> on {pending.symbol} won't be applied.",
                parse_mode='HTML'
            )
            await notification_sender.send_message(
                f"🚫 Brain action skipped by you\n"
                f"<b>{pending.action}</b> on {pending.symbol}\n"
                f"Reason given: {pending.reason}",
                category='approval_outcome',
            )
        return

    # ── Symbol clarification pick ──────────────────────────────────────────
    if callback_data.startswith("symbol_pick:"):
        parts = callback_data.split(":", 2)
        if len(parts) != 3:
            await query.edit_message_text("Something went wrong reading that pick — try /symbol TICKER instead.")
            return
        _, signal_id, symbol = parts
        from src.services.signal_clarification_service import signal_clarification_service
        ok, message = await signal_clarification_service.resolve(signal_id, symbol)
        await query.edit_message_text(message, parse_mode='HTML')
        return

    # ── Signal approve/reject ──────────────────────────────────────────────
    if ":" not in callback_data:
        await query.edit_message_text("Couldn't read that action — try again.")
        return

    action, signal_id = callback_data.split(":", 1)
    pending = approval_queue.get_pending_signal(signal_id)

    if not pending:
        # Signal not in the in-memory queue — check whether it still exists in the DB.
        # This happens when the bot restarts and the queue is wiped while old approval
        # messages are still sitting in Telegram.
        try:
            db_signal = await db_service.db.signal.find_unique(where={"id": signal_id})
        except Exception:
            db_signal = None

        if db_signal and db_signal.status == "AWAITING_APPROVAL":
            if action == "reject":
                # Can reject by updating the DB directly — no in-memory state needed.
                await db_service.db.signal.update(
                    where={"id": signal_id},
                    data={"status": "REJECTED", "rejectionReason": "Rejected via Telegram button (after bot restart)"},
                )
                logger.info(f"❌ Signal {signal_id[:8]}... rejected via button (post-restart DB path)")
                await query.edit_message_text(
                    "Signal rejected — it was queued before the last bot restart so it won't be executed."
                )
            else:
                # Cannot approve: we need the live TradingSignal + RiskAssessment objects
                # to place the trade, and those are lost on restart.
                await query.edit_message_text(
                    "⚠️ Can't approve — the bot was restarted and this signal's details were lost.\n\n"
                    "To trade this setup, re-send the original signal message and approve the new request."
                )
        else:
            await query.edit_message_text(
                "This signal is no longer in the queue — it may have timed out or already been handled."
            )
        return

    if action == "approve":
        if not approval_queue.approve_signal(signal_id):
            await query.edit_message_text("Couldn't approve — the signal may have just expired.")
            return

        await db_service.update_signal_status(signal_id, "PROCESSING")
        logger.info(f"✅ Signal {signal_id[:8]}... approved via inline button")

        channel_name = getattr(pending.signal, 'channel_name', None) or getattr(pending.signal, 'channel_id', None)
        channel_str = str(channel_name) if channel_name else "Unknown"
        order_type = getattr(pending.signal, 'order_type', None)
        direction_str = order_type.value if hasattr(order_type, 'value') else (str(order_type) if order_type else "N/A")

        await query.edit_message_text(
            f"Placing <b>{direction_str} {pending.signal.symbol}</b> — from {channel_str}",
            parse_mode='HTML'
        )

        try:
            await trading_service.execute_after_approval(
                pending.signal, pending.risk_assessment, signal_id
            )
        except Exception as e:
            logger.error(f"Failed to execute approved trade: {e}")
            await query.message.reply_text(f"Trade failed to execute: {e}")

    elif action == "reject":
        rejected = approval_queue.reject_signal(signal_id, "Rejected via inline button")
        if not rejected:
            await query.edit_message_text("Couldn't reject — the signal may have already been processed.")
            return

        logger.info(f"❌ Signal {signal_id[:8]}... rejected via inline button")

        order_type = getattr(pending.signal, 'order_type', None)
        direction_str = order_type.value if hasattr(order_type, 'value') else (str(order_type) if order_type else "N/A")

        await query.edit_message_text(
            f"Skipped — <b>{direction_str} {pending.signal.symbol}</b> won't be placed.",
            parse_mode='HTML'
        )


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

def register_approval_commands(application: Application):
    """Register all command handlers with the bot application."""
    application.add_handler(CommandHandler("execute", execute_command))
    application.add_handler(CommandHandler("reject", reject_command))
    application.add_handler(CommandHandler("pending", pending_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("symbol", symbol_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    logger.info(
        "✅ Commands registered: /execute, /reject, /pending, /status, "
        "/positions, /balance, /help, /pause, /resume, /symbol + inline buttons"
    )
