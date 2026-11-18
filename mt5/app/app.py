# Eventlet monkey-patch MUST be the very first thing imported so stdlib socket/threading
# are cooperatively patched before any other module pulls them in.
import os
USE_EVENTLET = os.environ.get("USE_EVENTLET", "1") != "0"
if USE_EVENTLET:
    try:
        import eventlet
        eventlet.monkey_patch()
    except ImportError:
        USE_EVENTLET = False

import logging
import logging.handlers
import signal
import atexit
from flask import Flask, jsonify, request
from flask_socketio import SocketIO
from dotenv import load_dotenv
import MetaTrader5 as mt5
from flasgger import Swagger
from werkzeug.middleware.proxy_fix import ProxyFix
from swagger import swagger_config

from routes.health    import health_bp
from routes.symbol    import symbol_bp
from routes.data      import data_bp
from routes.position  import position_bp
from routes.order     import order_bp
from routes.history   import history_bp
from routes.error     import error_bp
from routes.seasonal  import seasonal_bp
from routes.trade_lifecycle import trade_lifecycle_bp
from routes.websocket import websocket_bp
from routes.metrics   import metrics_bp
from routes.protection import protection_bp
from routes.mt5_auth  import mt5_auth_bp
from middleware.logging_mw import register as register_logging

load_dotenv()

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("LOG_FILE", "")  # if set, enable rotating file handler
LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))  # 10 MB
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 5))

_log_format = "%(asctime)s %(levelname)s %(name)s  %(message)s"
_handlers = [logging.StreamHandler()]
if LOG_FILE:
    try:
        os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
        _handlers.append(
            logging.handlers.RotatingFileHandler(
                LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
            )
        )
    except Exception as _e:  # noqa: BLE001 - log setup must not crash the app
        print(f"WARN: could not configure rotating log file {LOG_FILE}: {_e}")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=_log_format,
    handlers=_handlers,
)
logger = logging.getLogger(__name__)

# Suppress werkzeug HTTP access logs if LOG_LEVEL is WARNING or higher
if LOG_LEVEL in ("WARNING", "ERROR", "CRITICAL"):
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["PREFERRED_URL_SCHEME"] = "http"
app.config["JSON_SORT_KEYS"] = False
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_LENGTH", 1 * 1024 * 1024))  # 1 MB cap

# ── Fast JSON via orjson (3-5x faster than stdlib json) ───────────────────────
# Drop-in replaces Flask's response serializer when orjson is installed. Falls
# back silently to stdlib if orjson is unavailable.
try:
    import orjson  # type: ignore

    class _OrjsonProvider:
        """Minimal Flask 2.2+ JSON provider backed by orjson."""
        def __init__(self, app):
            self.app = app

        def dumps(self, obj, **kwargs):
            opts = orjson.OPT_NON_STR_KEYS
            return orjson.dumps(obj, option=opts).decode("utf-8")

        def loads(self, s, **kwargs):
            if isinstance(s, str):
                s = s.encode("utf-8")
            return orjson.loads(s)

        def response(self, *args, **kwargs):
            obj = args[0] if args else kwargs
            data = orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS)
            return self.app.response_class(data, mimetype="application/json")

    # Flask >=2.2 uses .json provider; older Flask uses encoder/decoder
    if hasattr(app, "json"):
        app.json = _OrjsonProvider(app)
    logger.info("orjson enabled for JSON serialization")
except ImportError:
    logger.info("orjson not installed — using stdlib json (install orjson for faster responses)")

# Initialize SocketIO
# In prod set WS_ALLOWED_ORIGINS to an explicit comma-separated origin list.
# Default still permits localhost wildcards for dev convenience.
_default_origins = "http://localhost:*,http://127.0.0.1:*"
allowed_origins = [o.strip() for o in os.environ.get("WS_ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]
if any(o == "*" for o in allowed_origins):
    logger.warning("WS_ALLOWED_ORIGINS contains '*' — this is unsafe in production.")

_async_mode = "eventlet" if USE_EVENTLET else "threading"
socketio = SocketIO(app, cors_allowed_origins=allowed_origins, async_mode=_async_mode)
logger.info("SocketIO async_mode=%s", _async_mode)

# Initialize socketio in websocket module
from routes.websocket import init_socketio
init_socketio(socketio)

# Initialize protection service
from services.equity_protection import init_protection_service
init_protection_service(socketio)

Swagger(app, config=swagger_config)
register_logging(app)

# Blueprints
for bp in [health_bp, symbol_bp, data_bp, position_bp, order_bp, history_bp, error_bp, seasonal_bp, trade_lifecycle_bp, websocket_bp, metrics_bp, protection_bp, mt5_auth_bp]:
    app.register_blueprint(bp)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


@app.route("/favicon.ico")
def favicon():
    return "", 204


# ── Global error handlers ─────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    from errors import ValidationError
    from utils.error_handler import format_error_response
    error = ValidationError("Route not found", endpoint=request.path if hasattr(request, 'path') else None)
    return format_error_response(error, 404)


@app.errorhandler(405)
def method_not_allowed(e):
    from errors import ValidationError
    from utils.error_handler import format_error_response
    error = ValidationError("Method not allowed", endpoint=request.path if hasattr(request, 'path') else None)
    return format_error_response(error, 405)


@app.errorhandler(500)
def internal_error(e):
    logger.error("Unhandled 500: %s", e)
    from errors import MT5APIError
    from utils.error_handler import format_error_response
    error = MT5APIError("Internal server error", endpoint=request.path if hasattr(request, 'path') else None)
    return format_error_response(error, 500)


# ── Graceful shutdown ─────────────────────────────────────────────────────────
_shutdown_called = False


def _graceful_shutdown(*_args):
    """Stop background threads, flush state, and tear down MT5 cleanly."""
    global _shutdown_called
    if _shutdown_called:
        return
    _shutdown_called = True
    logger.info("Shutdown signal received — stopping protection service and MT5...")
    try:
        from services.equity_protection import get_protection_service
        svc = get_protection_service()
        if svc:
            svc.stop()
            # Give heartbeat/monitor threads a moment to exit their sleep loops
            for t in (getattr(svc, "heartbeat_thread", None), getattr(svc, "monitor_thread", None)):
                if t and t.is_alive():
                    t.join(timeout=3.0)
    except Exception as e:
        logger.error("Error stopping protection service: %s", e)
    try:
        mt5.shutdown()
    except Exception as e:
        logger.error("Error during mt5.shutdown(): %s", e)
    logger.info("Shutdown complete.")


atexit.register(_graceful_shutdown)
for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, _graceful_shutdown)
    except (ValueError, OSError):
        # signal.signal only works in main thread; safe to skip otherwise
        pass


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("MT5_API_PORT", 5000))

    # Try env-var credentials → persisted file → bare initialize (attach existing terminal)
    from services.mt5_session import bootstrap_from_env_or_disk
    boot = bootstrap_from_env_or_disk()
    if boot.get("ok"):
        logger.info("MT5 initialized. Starting Flask-SocketIO (%s) on port %d", _async_mode, port)
    else:
        # Don't refuse to start — the operator can call POST /mt5/login to connect at runtime.
        logger.warning(
            "MT5 not connected at startup (%s). API will start; use POST /mt5/login to connect.",
            boot.get("error"),
        )

    # When eventlet is monkey-patched, socketio.run() uses eventlet's production WSGI
    # server (not Werkzeug dev server). This is the supported prod path under Wine.
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
