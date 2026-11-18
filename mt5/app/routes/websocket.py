from flask import request, Blueprint, jsonify
import MetaTrader5 as mt5
import logging
import os
import threading
import time
from utils.mt5_cache import get_account_info as cached_account_info, get_symbol_tick as cached_tick
from flasgger import swag_from
from flask_socketio import emit
from middleware.auth import require_api_key, is_valid_api_key, extract_api_key
from errors import ValidationError
from utils.error_handler import format_error_response
from swagger_specs import (
    websocket_status_spec, get_all_subscriptions_spec, websocket_info_spec,
    get_clients_spec, broadcast_tick_rest_spec, subscribe_rest_spec,
    broadcast_position_rest_spec, broadcast_order_rest_spec
)

logger = logging.getLogger(__name__)

# Blueprint for WebSocket REST endpoints
websocket_bp = Blueprint("websocket", __name__)

# SocketIO instance - will be set from app.py
socketio = None

# Subscription management
subscriptions = {}  # {sid: {'symbols': set(), 'positions': bool, 'orders': bool, 'account': bool}}
subs_lock = threading.Lock()

# Hard cap on concurrent WS clients to prevent unbounded memory growth from
# misbehaving clients reconnecting in a loop. Tune via env var.
MAX_WS_CLIENTS = int(os.environ.get("MAX_WS_CLIENTS", 200))
# Per-client cap on subscribed symbols
MAX_WS_SYMBOLS_PER_CLIENT = int(os.environ.get("MAX_WS_SYMBOLS_PER_CLIENT", 50))


def handle_connect(auth=None):
    """Handle client connection. Rejects unauthenticated clients and connections beyond MAX_WS_CLIENTS."""
    # Same key as the REST API (audit finding M-07): the Origin allowlist only
    # stops browsers, any script could otherwise stream account and positions.
    if not is_valid_api_key(extract_api_key(request.headers, auth)):
        logger.warning("WS connection refused for sid=%s from %s: invalid API key", request.sid, request.remote_addr)
        return False
    with subs_lock:
        if len(subscriptions) >= MAX_WS_CLIENTS:
            logger.warning(
                "WS connection refused for sid=%s: cap reached (%d/%d)",
                request.sid, len(subscriptions), MAX_WS_CLIENTS,
            )
            emit('error', {'message': 'Server at capacity, try again later'})
            return False  # tells Flask-SocketIO to refuse the handshake
        subscriptions[request.sid] = {
            'symbols': set(), 'positions': False, 'orders': False, 'account': False
        }
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to MT5 WebSocket'})
    return True  # explicitly accept the connection


def handle_disconnect():
    """Handle client disconnection."""
    logger.info(f"Client disconnected: {request.sid}")
    with subs_lock:
        if request.sid in subscriptions:
            del subscriptions[request.sid]


def handle_subscribe(data):
    """
    Subscribe to real-time updates.
    Data: {symbols: ["EURUSD", "GBPUSD"], positions: true, orders: true, account: true}
    """
    try:
        with subs_lock:
            if request.sid in subscriptions:
                subs = subscriptions[request.sid]

                # Subscribe to symbols (enforce per-client cap)
                if 'symbols' in data:
                    incoming = set(data.get('symbols') or [])
                    remaining = MAX_WS_SYMBOLS_PER_CLIENT - len(subs['symbols'])
                    if remaining <= 0:
                        emit('error', {'message': f'Symbol subscription cap reached ({MAX_WS_SYMBOLS_PER_CLIENT})'})
                        return
                    if len(incoming) > remaining:
                        incoming = set(list(incoming)[:remaining])
                    subs['symbols'].update(incoming)

                # Subscribe to positions
                if data.get('positions'):
                    subs['positions'] = True

                # Subscribe to orders
                if data.get('orders'):
                    subs['orders'] = True

                # Subscribe to live account equity/balance updates
                if data.get('account'):
                    subs['account'] = True

        logger.info(f"Client {request.sid} subscribed: {data}")
        emit('subscribed', {'message': 'Subscription updated', 'data': data})
    except Exception as e:
        logger.error(f"Subscribe error: {e}")
        emit('error', {'message': str(e)})


def handle_unsubscribe(data):
    """
    Unsubscribe from real-time updates.
    Data: {symbols: ["EURUSD"], positions: true, orders: true}
    """
    try:
        with subs_lock:
            if request.sid in subscriptions:
                subs = subscriptions[request.sid]
                
                # Unsubscribe from symbols
                if 'symbols' in data:
                    for symbol in data['symbols']:
                        subs['symbols'].discard(symbol)
                
                # Unsubscribe from positions
                if data.get('positions'):
                    subs['positions'] = False

                # Unsubscribe from orders
                if data.get('orders'):
                    subs['orders'] = False

                # Unsubscribe from account updates
                if data.get('account'):
                    subs['account'] = False
        
        logger.info(f"Client {request.sid} unsubscribed: {data}")
        emit('unsubscribed', {'message': 'Subscription updated', 'data': data})
    except Exception as e:
        logger.error(f"Unsubscribe error: {e}")
        emit('error', {'message': str(e)})


def broadcast_tick(symbol, tick_data):
    """Broadcast tick data to all subscribers of `symbol`.

    Pre-collects target SIDs under the lock, then emits OUTSIDE the lock so a
    single slow client cannot stall ticks for everyone else. Socket.IO will
    serialize the payload once per emit; we still avoid the lock-while-IO
    anti-pattern of the previous implementation.
    """
    with subs_lock:
        targets = [sid for sid, subs in subscriptions.items() if symbol in subs.get('symbols', set())]
    for sid in targets:
        try:
            socketio.emit('tick', tick_data, room=sid)
        except Exception as e:
            logger.error(f"Error broadcasting tick to {sid}: {e}")


def broadcast_position_update(position_data):
    """Broadcast position update to subscribed clients."""
    with subs_lock:  # collect under the lock, emit outside it: one slow client must not stall everyone
        targets = [sid for sid, subs in subscriptions.items() if subs.get('positions', False)]
    for sid in targets:
        try:
            socketio.emit('position_update', position_data, room=sid)
        except Exception as e:
            logger.error(f"Error broadcasting positions to {sid}: {e}")


def broadcast_order_update(order_data):
    """Broadcast order update to subscribed clients."""
    with subs_lock:  # collect under the lock, emit outside it: one slow client must not stall everyone
        targets = [sid for sid, subs in subscriptions.items() if subs.get('orders', False)]
    for sid in targets:
        try:
            socketio.emit('order_update', order_data, room=sid)
        except Exception as e:
            logger.error(f"Error broadcasting orders to {sid}: {e}")


def broadcast_account_update(account_data):
    """Broadcast live account equity/balance data to subscribed clients."""
    with subs_lock:  # collect under the lock, emit outside it: one slow client must not stall everyone
        targets = [sid for sid, subs in subscriptions.items() if subs.get('account', False)]
    for sid in targets:
        try:
            socketio.emit('account_update', account_data, room=sid)
        except Exception as e:
            logger.error(f"Error broadcasting account to {sid}: {e}")


def _get_tick_interval():
    """Return the configured WebSocket update interval, falling back to 0.5s."""
    from services.equity_protection import get_protection_service
    svc = get_protection_service()
    if svc:
        return max(0.1, svc.ws_update_interval)
    return 0.5


def tick_stream_worker():
    """Background worker to stream ticks for subscribed symbols."""
    while True:
        try:
            with subs_lock:
                all_symbols = set()
                for subs in subscriptions.values():
                    all_symbols.update(subs.get('symbols', set()))

            # Determine what to broadcast this cycle
            with subs_lock:
                wants_account = any(s.get('account') for s in subscriptions.values())

            if not all_symbols and not wants_account:
                time.sleep(_get_tick_interval())
                continue

            for symbol in all_symbols:
                tick = cached_tick(symbol)
                if tick:
                    tick_data = {
                        'symbol': symbol,
                        'bid': tick.bid,
                        'ask': tick.ask,
                        'spread': round(tick.ask - tick.bid, 5),
                        'volume': tick.volume,
                        'time': tick.time,
                    }
                    broadcast_tick(symbol, tick_data)

            if wants_account:
                info = cached_account_info()
                if info:
                    broadcast_account_update({
                        'login': info.login,
                        'balance': info.balance,
                        'equity': info.equity,
                        'margin': info.margin,
                        'margin_free': info.margin_free,
                        'margin_level': info.margin_level,
                        'profit': info.profit,
                        'currency': info.currency,
                        'time': time.time(),
                    })

            time.sleep(_get_tick_interval())
        except Exception as e:
            logger.error(f"Tick stream error: {e}")
            time.sleep(1)


@websocket_bp.route("/ws/status", methods=["GET"])
@require_api_key
@swag_from(websocket_status_spec)
def websocket_status():
    with subs_lock:
        return jsonify({
            "connected_clients": len(subscriptions),
            "subscriptions": {sid: subs for sid, subs in subscriptions.items()}
        })


@websocket_bp.route("/ws/subscriptions", methods=["GET"])
@require_api_key
@swag_from(get_all_subscriptions_spec)
def get_all_subscriptions():
    with subs_lock:
        return jsonify({
            "total_clients": len(subscriptions),
            "subscriptions": {sid: subs for sid, subs in subscriptions.items()}
        })


def _build_ws_url():
    """Construct the WebSocket URL from request host + MT5_API_PORT env var."""
    host = request.host.split(':')[0]  # strip port from Host header
    port = os.environ.get("MT5_API_PORT", "5001")
    return f"ws://{host}:{port}"

@websocket_bp.route("/ws/info", methods=["GET"])
@require_api_key
@swag_from(websocket_info_spec)
def websocket_info():
    ws_url = _build_ws_url()
    return jsonify({
        "connection": {
            "url": ws_url,
            "protocol": "socket.io"
        },
        "events": {
            "connect": {
                "description": "Fired when client connects",
                "response": "connected event with message"
            },
            "disconnect": {
                "description": "Fired when client disconnects"
            },
            "subscribe": {
                "description": "Subscribe to real-time updates",
                "request": {
                    "symbols": ["EURUSD", "GBPUSD"],
                    "positions": True,
                    "orders": True,
                    "account": True
                },
                "response": "subscribed event with confirmation"
            },
            "unsubscribe": {
                "description": "Unsubscribe from updates",
                "request": {
                    "symbols": ["EURUSD"],
                    "positions": True,
                    "orders": False
                },
                "response": "unsubscribed event with confirmation"
            }
        },
        "broadcasts": {
            "tick": {
                "description": "Real-time price updates for subscribed symbols",
                "data": {
                    "symbol": "EURUSD",
                    "bid": 1.0850,
                    "ask": 1.0852,
                    "spread": 0.0002,
                    "time": 1713712345.678
                }
            },
            "position_update": {
                "description": "Position updates for subscribed clients"
            },
            "order_update": {
                "description": "Order updates for subscribed clients"
            },
            "account_update": {
                "description": "Live account equity/balance stream (subscribe with account: true)",
                "data": {
                    "login": 12345,
                    "balance": 10000.0,
                    "equity": 9950.0,
                    "margin": 500.0,
                    "margin_free": 9450.0,
                    "margin_level": 1990.0,
                    "profit": -50.0,
                    "currency": "USD",
                    "time": 1713712345.678
                }
            },
            "protection_alert": {
                "description": "Equity protection triggered alert",
                "data": {
                    "account_number": "12345",
                    "reason": "Daily equity drawdown of 1.5% exceeded limit of 1.0%",
                    "message": "⚠️ EQUITY PROTECTION TRIGGERED...",
                    "timestamp": "2026-04-21T22:00:00Z"
                }
            },
            "equity_update": {
                "description": "Real-time equity status updates",
                "data": {
                    "status": {
                        "account_number": "12345",
                        "equity": 9950.0,
                        "balance": 10000.0,
                        "daily_drawdown_pct": 0.5,
                        "total_drawdown_pct": 5.0
                    },
                    "timestamp": "2026-04-21T22:00:00Z"
                }
            },
            "protection_status": {
                "description": "Protection service status change (enabled/disabled)",
                "data": {
                    "enabled": True,
                    "timestamp": "2026-04-21T22:00:00Z"
                }
            },
            "account_blocked": {
                "description": "Account trading blocked event",
                "data": {
                    "account_number": "12345",
                    "reason": "Daily drawdown exceeded",
                    "timestamp": "2026-04-21T22:00:00Z"
                }
            },
            "account_unblocked": {
                "description": "Account trading unblocked event",
                "data": {
                    "account_number": "12345",
                    "timestamp": "2026-04-21T22:00:00Z"
                }
            }
        }
    })


@websocket_bp.route("/ws/clients", methods=["GET"])
@require_api_key
@swag_from(get_clients_spec)
def get_clients():
    with subs_lock:
        return jsonify({
            "total_clients": len(subscriptions),
            "clients": [{"session_id": sid} for sid in subscriptions.keys()]
        })


@websocket_bp.route("/ws/broadcast/tick", methods=["POST"])
@require_api_key
@swag_from(broadcast_tick_rest_spec)
def broadcast_tick_rest():
    try:
        data = request.get_json()
        if not data or "symbol" not in data:
            raise ValidationError("symbol required", field="symbol", endpoint="/ws/broadcast/tick")
        
        tick_data = {
            "symbol": data["symbol"],
            "bid": data.get("bid", 0),
            "ask": data.get("ask", 0),
            "spread": data.get("ask", 0) - data.get("bid", 0),
            "time": time.time()
        }
        broadcast_tick(data["symbol"], tick_data)
        return jsonify({"message": f"Tick broadcast to {len(subscriptions)} clients"})
    except Exception as e:
        return format_error_response(e, 400)


@websocket_bp.route("/ws/subscribe", methods=["POST"])
@require_api_key
@swag_from(subscribe_rest_spec)
def subscribe_rest():
    try:
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required", endpoint="/ws/subscribe")
        
        return jsonify({
            "message": "Use WebSocket client for real-time subscriptions. This endpoint is for testing only.",
            "websocket_info": f"Connect to {_build_ws_url()} and emit 'subscribe' event"
        })
    except Exception as e:
        return format_error_response(e, 400)


@websocket_bp.route("/ws/broadcast/position", methods=["POST"])
@require_api_key
@swag_from(broadcast_position_rest_spec)
def broadcast_position_rest():
    try:
        data = request.get_json()
        if not data or "position" not in data:
            raise ValidationError("position required", field="position", endpoint="/ws/broadcast/position")
        
        broadcast_position_update(data["position"])
        return jsonify({"message": f"Position broadcast to {len(subscriptions)} clients"})
    except Exception as e:
        return format_error_response(e, 400)


@websocket_bp.route("/ws/broadcast/order", methods=["POST"])
@require_api_key
@swag_from(broadcast_order_rest_spec)
def broadcast_order_rest():
    try:
        data = request.get_json()
        if not data or "order" not in data:
            raise ValidationError("order required", field="order", endpoint="/ws/broadcast/order")
        
        broadcast_order_update(data["order"])
        return jsonify({"message": f"Order broadcast to {len(subscriptions)} clients"})
    except Exception as e:
        return format_error_response(e, 400)


def init_socketio(socketio_instance):
    """Initialize socketio instance and register event handlers."""
    global socketio
    socketio = socketio_instance

    # Register event handlers
    socketio.on('connect')(handle_connect)
    socketio.on('disconnect')(handle_disconnect)
    socketio.on('subscribe')(handle_subscribe)
    socketio.on('unsubscribe')(handle_unsubscribe)

    # Start the tick stream worker in a separate thread
    global tick_thread
    tick_thread = threading.Thread(target=tick_stream_worker, daemon=True)
    tick_thread.start()
    logger.info("Tick stream worker started")

