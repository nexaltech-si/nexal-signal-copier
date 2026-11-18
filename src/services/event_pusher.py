"""
Event Pusher

Fans every bot notification out to the dashboard and to devices:

  1. Inbox    - stored in ``app_notifications`` (the dashboard bell).
  2. Live     - published on Redis ``notifications:events`` so open dashboards
                receive it instantly over SSE (/api/notifications/stream).
  3. Web Push - delivered to every registered browser/phone through its push
                service, so it lands on the lock screen even when the dashboard
                is closed. On iPhone this requires the dashboard to be added to
                the Home Screen (iOS 16.4+).

Every stage is isolated: a Redis outage or a dead push endpoint never blocks the
other stages, and nothing here ever raises into the caller.

``UnifiedNotificationSender`` calls ``push_from_sender`` for every Telegram send,
so any notification the bot already produces shows up here with no extra wiring.
Other code can call ``await event_pusher.push(...)`` directly.
"""
import asyncio
import base64
import html
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from loguru import logger

REDIS_CHANNEL = "notifications:events"

# Push services cap payloads at ~4KB; keep well under once JSON-encoded.
MAX_PUSH_BODY = 600
# Drop a subscription after this many consecutive non-fatal failures.
MAX_FAILURES = 5
# How long a push service keeps an undelivered message (device offline).
PUSH_TTL_SECONDS = 24 * 60 * 60

# Replies to the user's own commands - only useful inside the Telegram chat.
SKIP_CATEGORIES = {"command_response", "reply_unclear"}

TRADE_CATEGORIES = {
    "trade_executed", "trade_failed", "trade_closed", "order_cancelled",
    "rr_milestone", "position_management",
}
SIGNAL_CATEGORIES = {
    "signal_received", "signal_rejected", "signal_parse_failed",
    "brain_decision", "approval_outcome", "trade_plans",
}

URL_BY_TYPE = {"TRADE": "/account", "SIGNAL": "/", "SYSTEM": "/logs", "CONNECTION": "/connection"}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _val(x: Any) -> str:
    """Enum-or-plain value to display string."""
    if x is None:
        return ""
    return str(getattr(x, "value", x)).upper()


def _num(x: Any) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x):g}"
    except (TypeError, ValueError):
        return str(x)


def _clean_text(message: str) -> str:
    """Telegram HTML/Markdown message -> plain text."""
    text = re.sub(r"<br\s*/?>", "\n", message or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"(\*\*|__|`)", "", text)
    return text


def _split_title_body(message: str) -> Tuple[str, str]:
    lines = [ln.strip() for ln in _clean_text(message).splitlines()]
    lines = [ln for ln in lines if ln and not re.fullmatch(r"[━─—=\-_.•\s]+", ln)]
    if not lines:
        return "Notification", ""
    return lines[0][:120], "\n".join(lines[1:])


class EventPusher:
    def __init__(self):
        self._redis = None
        self._vapid_keys: Optional[Tuple[str, str]] = None  # (public, private) base64url
        self._vapid = None  # py_vapid.Vapid instance
        self._tasks: set = set()

    # ------------------------------------------------------------------ VAPID

    def _load_vapid_keys(self) -> Tuple[str, str]:
        """
        VAPID keypair identifying this server to push services.

        Uses VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY when set; otherwise generates a
        pair once and persists it next to the database, so subscriptions survive
        restarts. Changing the keys invalidates every existing subscription.
        """
        if self._vapid_keys:
            return self._vapid_keys

        pub, priv = os.getenv("VAPID_PUBLIC_KEY"), os.getenv("VAPID_PRIVATE_KEY")
        if pub and priv:
            self._vapid_keys = (pub.strip(), priv.strip())
            return self._vapid_keys

        path = os.getenv("VAPID_KEYS_FILE", "data/vapid_keys.json")
        try:
            with open(path) as f:
                stored = json.load(f)
            self._vapid_keys = (stored["publicKey"], stored["privateKey"])
            return self._vapid_keys
        except FileNotFoundError:
            pass

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        key = ec.generate_private_key(ec.SECP256R1())
        priv_raw = key.private_numbers().private_value.to_bytes(32, "big")
        pub_raw = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self._vapid_keys = (_b64url(pub_raw), _b64url(priv_raw))

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"publicKey": self._vapid_keys[0], "privateKey": self._vapid_keys[1]}, f)
        logger.success(f"🔑 Generated VAPID keys for Web Push ({path})")
        return self._vapid_keys

    def vapid_public_key(self) -> str:
        return self._load_vapid_keys()[0]

    def _vapid_signer(self):
        if self._vapid is None:
            from py_vapid import Vapid

            self._vapid = Vapid.from_raw(self._load_vapid_keys()[1].encode())
        return self._vapid

    @staticmethod
    def _vapid_subject() -> str:
        subject = os.getenv("VAPID_SUBJECT")
        if subject:
            return subject
        domain = os.getenv("DASHBOARD_DOMAIN")
        if domain:
            return f"https://{domain}"
        # Apple rejects localhost subjects - set VAPID_SUBJECT for iPhone delivery.
        return "mailto:admin@localhost"

    # ----------------------------------------------------------------- public

    async def push(
        self,
        title: str,
        body: str = "",
        *,
        type: str = "SYSTEM",
        severity: str = "INFO",
        category: Optional[str] = None,
        url: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        require_interaction: bool = False,
    ) -> Dict[str, int]:
        """Store, broadcast and push one event. Returns push delivery stats."""
        event = {
            "id": None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "type": type,
            "severity": severity,
            "title": title,
            "body": body or "",
            "url": url or URL_BY_TYPE.get(type, "/"),
            "data": data,
            "readAt": None,
        }

        event["id"] = await self._store(event)
        await self._publish(event)

        stats = {"delivered": 0, "failed": 0, "removed": 0}
        if await self._push_allowed(type, severity):
            stats = await self._send_web_push(event, require_interaction)
        return stats

    def push_from_sender(self, method_name: str, args: tuple, kwargs: dict, category: Optional[str]):
        """Fire-and-forget hook for UnifiedNotificationSender - never blocks Telegram."""
        try:
            event = self._event_from_sender(method_name, args, kwargs, category)
        except Exception as e:
            logger.debug(f"Event pusher: could not format {method_name}: {e}")
            return
        if not event:
            return
        task = asyncio.create_task(self._push_safely(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _push_safely(self, event: Dict[str, Any]):
        try:
            await self.push(**event)
        except Exception as e:
            logger.warning(f"Event pusher failed: {e}")

    # ------------------------------------------------------------- formatting

    def _event_from_sender(
        self, method: str, args: tuple, kwargs: dict, category: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        from src.services.notification_filter_service import METHOD_CATEGORY_MAP

        category = category or METHOD_CATEGORY_MAP.get(method)
        if category in SKIP_CATEGORIES:
            return None

        def sig_label(s) -> str:
            # order_type carries the direction (BUY/SELL); action is OPEN/CLOSE/MODIFY
            side = _val(getattr(s, "order_type", None))
            action = _val(getattr(s, "action", None))
            if action and action != "OPEN":
                side = f"{action.replace('_', ' ')} {side}".strip()
            return f"{side} {getattr(s, 'symbol', '') or ''}".strip()

        def sig_levels(s) -> str:
            tps = getattr(s, "take_profit", None) or []
            parts = [f"Entry {_num(getattr(s, 'entry_price', None)) if getattr(s, 'entry_price', None) else 'Market'}"]
            if getattr(s, "stop_loss", None):
                parts.append(f"SL {_num(s.stop_loss)}")
            if tps:
                parts.append("TP " + " / ".join(_num(t) for t in tps[:3]))
            return " · ".join(parts)

        a = args
        if method == "notify_signal_received":
            return dict(type="SIGNAL", severity="INFO", category=category,
                        title=f"New signal: {sig_label(a[0])}", body=sig_levels(a[0]))
        if method == "notify_signal_rejected":
            return dict(type="SIGNAL", severity="WARNING", category=category,
                        title=f"Signal rejected: {sig_label(a[0])}", body=str(a[1]))
        if method == "notify_trade_executed":
            signal, risk, result = a[0], a[1], a[2]
            lots = getattr(risk, "calculated_lot_size", None)
            price = getattr(result, "entry_price", None) or getattr(signal, "entry_price", None)
            body = f"{_num(lots)} lots @ {_num(price)}"
            if getattr(signal, "stop_loss", None):
                body += f" · SL {_num(signal.stop_loss)}"
            return dict(type="TRADE", severity="SUCCESS", category=category,
                        title=f"Trade opened: {sig_label(signal)}", body=body,
                        data={"positionId": getattr(result, "position_id", None)})
        if method == "notify_trade_failed":
            return dict(type="TRADE", severity="ERROR", category=category,
                        title=f"Trade failed: {sig_label(a[0])}", body=str(a[1]))
        if method == "notify_position_closed":
            signal, close_price, pl, pips = a[0], a[1], a[2], a[3]
            won = (pl or 0) >= 0
            return dict(type="TRADE", severity="SUCCESS" if won else "WARNING", category=category,
                        title=f"Closed {sig_label(signal)}: {'+' if won else '-'}${abs(pl or 0):,.2f}",
                        body=f"Closed @ {_num(close_price)} · {pips:+.1f} pips" if pips is not None else "")
        if method == "notify_error":
            return dict(type="SYSTEM", severity="ERROR", category=category,
                        title=f"Error: {a[0]}", body=str(a[1]))
        if method == "notify_risk_warning":
            return dict(type="SYSTEM", severity="WARNING", category=category,
                        title="Risk warning", body=str(a[0]))
        if method == "notify_bot_started":
            return dict(type="SYSTEM", severity="SUCCESS", category=category,
                        title="Bot started", body="Trading bot is online and monitoring signals")
        if method == "notify_bot_stopped":
            return dict(type="SYSTEM", severity="WARNING", category=category,
                        title="Bot stopped", body="Trading bot has shut down")
        if method == "notify_daily_summary":
            return dict(type="SYSTEM", severity="INFO", category=category,
                        title="Daily summary", body=", ".join(f"{k}: {v}" for k, v in (a[0] or {}).items())[:MAX_PUSH_BODY])
        if method == "notify_approval_request":
            signal, timeout = a[0], a[3]
            return dict(type="SIGNAL", severity="WARNING", category=category, require_interaction=True,
                        title=f"Approval needed: {sig_label(signal)}",
                        body=f"{sig_levels(signal)} · expires in {int(timeout)}s",
                        data={"signalId": a[2]})
        if method == "notify_approval_confirmed":
            return dict(type="SIGNAL", severity="SUCCESS", category=category,
                        title=f"Approved: {sig_label(a[0])}", body="Executing trade")
        if method == "notify_approval_timeout":
            return dict(type="SIGNAL", severity="WARNING", category=category,
                        title=f"Approval timed out: {sig_label(a[0])}", body="Signal was not executed")
        if method == "notify_brain_action_approval":
            action_id, symbol, action, reason = a[0], a[1], a[2], a[3]
            return dict(type="TRADE", severity="WARNING", category=category, require_interaction=True,
                        title=f"Brain wants to {str(action).replace('_', ' ').lower()} {symbol}",
                        body=str(reason), data={"actionId": action_id})
        if method == "send_symbol_picker":
            title, body = _split_title_body(a[0])
            return dict(type="SIGNAL", severity="WARNING", category=category,
                        require_interaction=True, title=title, body=body)
        if method == "send_message":
            title, body = _split_title_body(a[0])
            if category in TRADE_CATEGORIES:
                ntype = "TRADE"
            elif category in SIGNAL_CATEGORIES:
                ntype = "SIGNAL"
            else:
                ntype = "SYSTEM"
            if category in ("errors", "trade_failed"):
                severity = "ERROR"
            elif category in ("risk_alerts", "signal_rejected", "signal_parse_failed", "order_cancelled"):
                severity = "WARNING"
            elif category in ("trade_executed", "rr_milestone"):
                severity = "SUCCESS"
            else:
                severity = "INFO"
            return dict(type=ntype, severity=severity, category=category, title=title, body=body)

        logger.debug(f"Event pusher: no formatter for {method}")
        return None

    # ----------------------------------------------------------------- stages

    @staticmethod
    def _db():
        from src.core.prisma_client import prisma_client

        return prisma_client.client

    async def _store(self, event: Dict[str, Any]) -> Optional[str]:
        try:
            row = await self._db().appnotification.create(
                data={
                    "category": event["category"],
                    "type": event["type"],
                    "severity": event["severity"],
                    "title": event["title"],
                    "body": event["body"],
                    "url": event["url"],
                    "data": json.dumps(event["data"], default=str) if event["data"] else None,
                }
            )
            event["createdAt"] = row.createdAt.isoformat()
            return row.id
        except Exception as e:
            logger.warning(f"Event pusher: could not store notification: {e}")
            return f"tmp-{datetime.now(timezone.utc).timestamp()}"

    async def _publish(self, event: Dict[str, Any]):
        url = os.getenv("REDIS_URL")
        if not url:
            return
        try:
            if self._redis is None:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(url, socket_connect_timeout=3)
            await self._redis.publish(REDIS_CHANNEL, json.dumps(event, default=str))
        except Exception as e:
            logger.debug(f"Event pusher: Redis publish failed: {e}")

    async def _push_allowed(self, ntype: str, severity: str) -> bool:
        """Respect the dashboard Settings → Notifications switches."""
        try:
            row = await self._db().query_first(
                "SELECT notificationsEnabled, tradeNotificationsEnabled, "
                "systemNotificationsEnabled, errorNotificationsEnabled FROM user_settings LIMIT 1"
            )
        except Exception:
            return True
        if not row:
            return True
        if not row.get("notificationsEnabled", True):
            return False
        if ntype == "TRADE" and not row.get("tradeNotificationsEnabled", True):
            return False
        if ntype in ("SYSTEM", "CONNECTION") and not row.get("systemNotificationsEnabled", True):
            return False
        if severity == "ERROR" and not row.get("errorNotificationsEnabled", True):
            return False
        return True

    async def _send_web_push(self, event: Dict[str, Any], require_interaction: bool) -> Dict[str, int]:
        stats = {"delivered": 0, "failed": 0, "removed": 0}
        try:
            db = self._db()
            subs = await db.pushsubscription.find_many()
            if not subs:
                return stats
            unread = await db.appnotification.count(where={"readAt": None})
        except Exception as e:
            logger.warning(f"Event pusher: could not load push subscriptions: {e}")
            return stats

        body = event["body"]
        payload = json.dumps({
            "id": event["id"],
            "title": event["title"],
            "body": body if len(body) <= MAX_PUSH_BODY else body[: MAX_PUSH_BODY - 1] + "…",
            "url": event["url"],
            "type": event["type"],
            "severity": event["severity"],
            "tag": event["id"],
            "badge": unread,
            "requireInteraction": require_interaction,
            "timestamp": event["createdAt"],
        })
        urgency = "high" if require_interaction or event["severity"] in ("ERROR", "WARNING") or event["type"] == "TRADE" else "normal"

        results = await asyncio.gather(
            *(asyncio.to_thread(self._send_one, s, payload, urgency) for s in subs),
            return_exceptions=True,
        )

        now = datetime.now(timezone.utc)
        for sub, result in zip(subs, results):
            outcome = result if isinstance(result, str) else "error"
            try:
                if outcome == "ok":
                    stats["delivered"] += 1
                    await db.pushsubscription.update(
                        where={"id": sub.id}, data={"lastSuccessAt": now, "failureCount": 0}
                    )
                elif outcome == "gone" or sub.failureCount + 1 >= MAX_FAILURES:
                    stats["removed"] += 1
                    await db.pushsubscription.delete(where={"id": sub.id})
                else:
                    stats["failed"] += 1
                    await db.pushsubscription.update(
                        where={"id": sub.id}, data={"failureCount": sub.failureCount + 1}
                    )
            except Exception as e:
                logger.debug(f"Event pusher: subscription bookkeeping failed: {e}")

        if stats["failed"] or stats["removed"]:
            logger.info(f"📲 Web Push: {stats}")
        return stats

    def _send_one(self, sub, payload: str, urgency: str) -> str:
        """Blocking send of one push (runs in a worker thread)."""
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload,
                vapid_private_key=self._vapid_signer(),
                # Fresh dict per send: pywebpush writes the endpoint's "aud" into it.
                vapid_claims={"sub": self._vapid_subject()},
                ttl=PUSH_TTL_SECONDS,
                headers={"Urgency": urgency},
                timeout=10,
            )
            return "ok"
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                return "gone"
            logger.warning(f"Web Push to {sub.endpoint[:40]}… failed ({status}): {e}")
            return "error"
        except Exception as e:
            logger.warning(f"Web Push to {sub.endpoint[:40]}… failed: {e}")
            return "error"


# Singleton instance
event_pusher = EventPusher()
