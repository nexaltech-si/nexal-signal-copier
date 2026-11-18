# MetaTrader 5 REST + WebSocket API

A containerized MetaTrader 5 stack: MT5 terminal running under Wine on Debian, fronted by a Flask + Flask-SocketIO server that exposes a complete REST API for orders, positions, market data, and account management — plus a WebSocket feed for live ticks and account updates and a built-in equity-protection / drawdown engine that auto-liquidates and blocks trading when configurable risk limits are hit.

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [MT5 Login (Broker Connection)](#mt5-login-broker-connection)
- [API Authentication](#api-authentication)
- [REST API Reference](#rest-api-reference)
  - [Health & Account](#health--account)
  - [MT5 Session](#mt5-session)
  - [Symbols](#symbols)
  - [Market Data](#market-data)
  - [Orders](#orders)
  - [Positions](#positions)
  - [History](#history)
  - [Trade Lifecycle](#trade-lifecycle)
  - [Equity Protection](#equity-protection)
  - [WebSocket Management](#websocket-management)
  - [Metrics & Diagnostics](#metrics--diagnostics)
- [WebSocket Protocol](#websocket-protocol)
- [Equity Protection — How It Works](#equity-protection--how-it-works)
- [Performance & Caching](#performance--caching)
- [Logging](#logging)
- [Graceful Shutdown](#graceful-shutdown)
- [Production Checklist](#production-checklist)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Docker container                            │
│                                                                  │
│  ┌──────────────┐         ┌──────────────────────────────────┐  │
│  │ Wine + MT5   │ ◄────── │  Flask + Flask-SocketIO (eventlet)│  │
│  │ terminal64   │  IPC    │  REST  :5001                      │  │
│  └──────────────┘         │  WS    :5001 (same port)         │  │
│         ▲                  │                                   │  │
│         │                  │  ┌────────────────────────────┐  │  │
│         │  reconnect       │  │ Equity Protection (thread) │  │  │
│         └──────────────────┤  │ - heartbeat every Ns       │  │  │
│                            │  │ - auto-liquidate on breach │  │  │
│                            │  │ - blocks new orders        │  │  │
│                            │  └────────────────────────────┘  │  │
│                            │                                   │  │
│                            │  ┌────────────────────────────┐  │  │
│                            │  │ MT5 Session manager        │  │  │
│                            │  │ - holds login credentials  │  │  │
│                            │  │ - heartbeat reconnect      │  │  │
│                            │  └────────────────────────────┘  │  │
│                            └──────────────────────────────────┘  │
│                                                                  │
│  Volumes: /config (Wine), /protection_config (state + creds)    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTP / WebSocket (X-API-Key)
                              │
                          your client
```

Key components:

| Component | File | Role |
|---|---|---|
| Flask API | `app/app.py` | HTTP routes, blueprints, eventlet WSGI |
| WebSocket | `app/routes/websocket.py` | Tick stream, account stream, broadcasts |
| MT5 session manager | `app/services/mt5_session.py` | Login/logout/reconnect with stored credentials |
| Equity protection | `app/services/equity_protection.py` | Drawdown engine, blocking, auto-liquidation |
| MT5 cache | `app/utils/mt5_cache.py` | TTL cache for hot read-only MT5 calls |
| Validation | `app/utils/validation_schemas.py` | Marshmallow request schemas |
| Auth middleware | `app/middleware/auth.py` | API key + trading-blocked decorators |
| Logging middleware | `app/middleware/logging_mw.py` | Per-request structured access log |

---

## Quick Start

### 1. Clone & configure

```bash
git clone <your-repo> mt5-api
cd mt5-api
cp .env.example .env   # edit values
```

### 2. Minimal `.env`

```dotenv
# MT5 broker credentials (auto-login at startup; alternative: POST /mt5/login)
MT5_LOGIN=12345678
MT5_PASSWORD=your-trading-password
MT5_SERVER=ICMarketsSC-Demo

# API security (recommended for any non-localhost deployment)
MT5_API_KEY=replace-with-a-long-random-string

# WebSocket origins (comma-separated, no spaces)
WS_ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.com

# Optional: VNC + Traefik (if using the bundled docker-compose)
CUSTOM_USER=admin
PASSWORD=vnc-password
VNC_DOMAIN=mt5.example.com
TRAEFIK_DOMAIN=traefik.example.com
TRAEFIK_USERNAME=admin
ACME_EMAIL=you@example.com
```

### 3. Start

```bash
docker-compose up -d
docker-compose logs -f mt5
```

Once you see `MT5 initialized. Starting Flask-SocketIO (eventlet) on port 5001`, the API is ready.

### Security patch image

A full `docker compose build` of this image is not reliable (Debian 11 base, out of support).
Security fixes go into `security-patch.sh`, which the Dockerfile runs at the end and which can
also be layered on the image that is running now:

```bash
docker tag mt5-mt5:latest mt5-mt5:pre-$(date +%Y%m%d)          # rollback point
printf 'FROM mt5-mt5:pre-%s\nCOPY security-patch.sh /tmp/\nRUN bash /tmp/security-patch.sh && rm /tmp/security-patch.sh\n' \
  "$(date +%Y%m%d)" | docker build -t mt5-mt5:latest -f - .
docker compose up -d --no-build --force-recreate               # terminal is back after ~2 min
```

Debian 11's security updates now live on `archive.debian.org` only; the script fetches from
there. Debian 11 gets no new fixes, so moving the base to Debian 12 is the long-term fix.

### 4. Smoke test

```bash
# Health needs no key:
curl http://localhost:5001/health

# With API key:
curl -H "X-API-Key: $MT5_API_KEY" http://localhost:5001/account_info
```

### 5. Swagger UI

Open `http://localhost:5001/apidocs/` for the interactive OpenAPI explorer — every endpoint is documented with request and response schemas.

---

## Environment Variables

### MT5 connection

| Var | Default | Description |
|---|---|---|
| `MT5_LOGIN` | _(empty)_ | Broker account number — if set with `MT5_PASSWORD` and `MT5_SERVER`, the API auto-logs in at startup |
| `MT5_PASSWORD` | _(empty)_ | Broker account password |
| `MT5_SERVER` | _(empty)_ | Exact broker server name (case-sensitive, e.g. `ICMarketsSC-Demo`) |
| `MT5_PATH` | _(auto)_ | Optional absolute path to `terminal64.exe` (Wine path) |
| `MT5_TIMEOUT` | `60000` | `mt5.initialize()` timeout in ms |
| `MT5_PERSIST_LOGIN` | `0` | Set to `1` to persist credentials to `/protection_config/mt5_session.json` (chmod 0600) so the container survives restarts without re-login |

If none of the above are set the API still starts — call `POST /mt5/login` at runtime.

### API security

| Var | Default | Description |
|---|---|---|
| `MT5_API_KEY` | _(empty)_ | Shared secret. **If unset, protected endpoints fail closed (503)** unless `MT5_API_AUTH_DISABLED=true` (local development only). Send as `X-API-Key: <value>` or `Authorization: Bearer <value>` |
| `MT5_API_AUTH_DISABLED` | `false` | `true` turns authentication off. Never use in production. |
| `PROTECTION_DAY_OFFSET_HOURS` | `0` | Initial default only. The offset (`day_offset_hours`) lives in the protection config and is edited on the dashboard Account page (Daily Reset Offset), applied immediately: it shifts the equity-protection "trading day" (daily-drawdown reset) from the container's local date, e.g. `3` if the broker's midnight is 03:00 on the container clock. |
| `MAX_CONTENT_LENGTH` | `1048576` | Max request body size in bytes (1 MB default) |

### Server / network

| Var | Default | Description |
|---|---|---|
| `MT5_API_PORT` | `5000` (Docker forces `5001`) | HTTP port |
| `USE_EVENTLET` | `1` | Set to `0` to fall back to threading mode (debug only) |
| `WS_ALLOWED_ORIGINS` | `http://localhost:*,http://127.0.0.1:*` | Comma-separated SocketIO CORS origins |
| `MAX_WS_CLIENTS` | `200` | Hard cap on concurrent WebSocket clients |
| `MAX_WS_SYMBOLS_PER_CLIENT` | `50` | Max symbols a single client can subscribe to |

### Logging

| Var | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`. `WARNING+` silences werkzeug request spam |
| `LOG_FILE` | _(stdout only)_ | Path to a rotating log file. If set, both stdout and file get logs |
| `LOG_MAX_BYTES` | `10485760` | Rotation size (10 MB) |
| `LOG_BACKUP_COUNT` | `5` | Number of rotated files to keep |

### MT5 read-cache (display-only)

These control the TTL cache for hot read-only MT5 calls. They do **not** affect equity protection (which always reads fresh).

| Var | Default | Description |
|---|---|---|
| `MT5_ACCOUNT_INFO_TTL` | `0.1` | Seconds. Multiple readers within this window share one Wine IPC call |
| `MT5_TICK_TTL` | `0.1` | Same, for `symbol_info_tick(symbol)` |

---

## MT5 Login (Broker Connection)

The API supports three ways to connect to a broker — tried in this order at startup:

### 1. Env vars (preferred)

Set `MT5_LOGIN` + `MT5_PASSWORD` + `MT5_SERVER` (and optionally `MT5_PATH`, `MT5_TIMEOUT`). The API logs in automatically.

### 2. Persisted credentials file

If `MT5_PERSIST_LOGIN=1` and a previous successful login is saved to `/protection_config/mt5_session.json`, the API restores it.

### 3. Runtime login via API

```bash
curl -X POST http://localhost:5001/mt5/login \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MT5_API_KEY" \
  -d '{
    "login":   12345678,
    "password":"your-password",
    "server":  "ICMarketsSC-Demo"
  }'
```

The credentials are held in process memory (and saved to disk if `MT5_PERSIST_LOGIN=1`). The equity-protection heartbeat re-uses them automatically to reconnect after any drop.

> **Finding your server name:** open MT5 manually once via VNC, click *File → Login to Trade Account*. The exact string in the **Server** dropdown is what you must put in `MT5_SERVER`. It is case-sensitive.

### Logout

```bash
curl -X POST http://localhost:5001/mt5/logout -H "X-API-Key: $MT5_API_KEY"
```

### Status

```bash
curl http://localhost:5001/mt5/login_status -H "X-API-Key: $MT5_API_KEY"
```

Returns `{logged_in, login, server, connected, account, last_error}` — password is **never** returned.

---

## API Authentication

| Mode | Trigger | Behavior |
|---|---|---|
| **Disabled** | `MT5_API_KEY` unset/empty | Every endpoint accepts unauthenticated requests. Fine for `localhost:` only |
| **Enabled** | `MT5_API_KEY=<value>` | Every protected endpoint requires `X-API-Key: <value>` (or `Authorization: Bearer <value>`); otherwise returns `401` |

Two endpoints are unauthenticated regardless: `/health` and `/version` (so orchestrators can probe them).

### Trading block enforcement

Order-placement endpoints (`/order`, `/limit_order`) are also gated by `@require_trading_not_blocked`. When equity protection has fired they return:

```json
HTTP 403
{ "error": "Trading blocked", "reason": "Daily drawdown of 3.21% exceeded limit of 3.00%" }
```

Position-closing endpoints are intentionally **not** blocked — you can always reduce exposure.

---

## REST API Reference

All paths are relative to `http://<host>:<port>`. **Auth column**: 🔐 = needs `X-API-Key` if `MT5_API_KEY` is set · 🚫 = also blocked when equity protection trips.

### Health & Account

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | — | Liveness probe — returns `{status, mt5_connected, mt5_initialized}` |
| GET | `/` | — | Alias for `/health` |
| GET | `/version` | — | MT5 build/date/revision |
| GET | `/account_info` | 🔐 | Balance, equity, margin, leverage, profit (cached ~100ms) |
| GET | `/terminal_info` | 🔐 | Terminal build, paths, connection flags |

### MT5 Session

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/mt5/login` | 🔐 | Login to broker (body: `login`, `password`, `server`, `path?`, `timeout?`) |
| POST | `/mt5/logout` | 🔐 | Disconnect and forget credentials |
| GET | `/mt5/login_status` | 🔐 | Current session info (no password) |

### Symbols

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/symbols` | 🔐 | All symbols in Market Watch |
| GET | `/symbols/search?group=*USD*` | 🔐 | Filter by group pattern |
| GET | `/symbol_info/<symbol>` | 🔐 | Full SymbolInfo (digits, contract size, swap, etc.) |
| GET | `/symbol_info_tick/<symbol>` | 🔐 | Latest bid/ask/volume tick |
| GET | `/market_book/<symbol>` | 🔐 | Depth-of-Market (DOM) |

### Market Data

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/fetch_data_pos?symbol=&timeframe=&num_bars=` | 🔐 | OHLCV bars from current bar backwards |
| GET | `/fetch_data_range?symbol=&timeframe=&from_date=&to_date=` | 🔐 | OHLCV bars in ISO date range |
| GET | `/fetch_ticks?symbol=&from_date=&count=&flags=` | 🔐 | Ticks from datetime, capped at 100k |
| GET | `/fetch_ticks_range?symbol=&from_date=&to_date=` | 🔐 | Ticks in date range |

Timeframes: `M1, M2, M3, M4, M5, M6, M10, M12, M15, M20, M30, H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1`.

### Orders

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/order` | 🔐🚫 | Send market order |
| POST | `/limit_order` | 🔐🚫 | Send pending order |
| POST | `/cancel_order` | 🔐 | Cancel a pending order by ticket |
| POST | `/modify_order` | 🔐 | Modify pending order (price, SL, TP, expiration) |
| POST | `/close_all_orders` | 🔐 | Cancel all pending orders (filterable by `magic`/`symbol`/`order_type`) |

**Market order body:**
```json
{
  "symbol":   "EURUSD",
  "volume":   0.10,
  "type":     "BUY",                    // BUY|SELL
  "sl":       1.0820,                   // optional
  "tp":       1.0950,                   // optional
  "deviation":20,                       // optional, default 20
  "magic":    1001,                     // optional
  "comment":  "strategy-A",             // optional, max 128 chars
  "type_filling": "ORDER_FILLING_IOC"   // optional: FOK|IOC|RETURN
}
```

**Pending order body:**
```json
{
  "symbol": "EURUSD",
  "volume": 0.10,
  "type":   "BUY_LIMIT",                // BUY_LIMIT|SELL_LIMIT|BUY_STOP|SELL_STOP|BUY_STOP_LIMIT|SELL_STOP_LIMIT
  "price":  1.0850,
  "stoplimit_price": 1.0855,            // required for *_STOP_LIMIT
  "sl": 1.0820, "tp": 1.0950,
  "expiration": "2026-12-31T23:59:59Z", // optional ISO8601 → ORDER_TIME_SPECIFIED
  "deviation": 20, "magic": 1001
}
```

### Positions

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/positions_total` | 🔐 | Count |
| GET | `/get_positions?magic=` | 🔐 | Open positions |
| GET | `/get_orders?magic=` | 🔐 | Pending orders |
| POST | `/close_position` | 🔐 | Close one position by ticket |
| POST | `/close_partial` | 🔐 | Partial close (requires `volume` < open volume) |
| POST | `/close_all_positions` | 🔐 | Close all (filter `order_type` = `all`/`buy`/`sell`, `magic`) |
| POST | `/close_profitable` | 🔐 | Close winners only |
| POST | `/close_losing` | 🔐 | Close losers only |
| POST | `/close_symbol` | 🔐 | Close all positions on a symbol |
| POST | `/modify_sl_tp` | 🔐 | Modify stop loss / take profit on a position |

### History

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/history_deals_get?from_date=&to_date=&symbol=&magic=&position=` | 🔐 | Deals in range |
| GET | `/history` | 🔐 | Alias for `history_deals_get` |
| GET | `/history_orders_get?ticket=` _or_ `?from_date=&to_date=` | 🔐 | Historical orders |
| GET | `/get_deal_from_ticket?ticket=` | 🔐 | Aggregated P&L for one position ticket |
| GET | `/get_order_from_ticket?ticket=` | 🔐 | Single historical order |
| GET | `/account_stats?from_date=&to_date=` | 🔐 | Win rate / profit factor / drawdown across a window |

### Trade Lifecycle

Unified view across pending orders, open positions, and closed deals.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/trade_lifecycle?ticket=` | 🔐 | Full picture: pending order, open position, deals, closed status |
| GET | `/trade_status?ticket=` | 🔐 | Quick status: `PENDING`/`RUNNING`/`CLOSED_PROFIT`/`CLOSED_LOSS`/etc. |
| POST | `/trade_batch_status` | 🔐 | Same for an array of tickets |
| GET | `/trade_search?symbol=&magic=&status=&from_date=&to_date=` | 🔐 | Search closed trades |
| GET | `/api/mt5/history` | 🔐 | Alias of `trade_search` |

### Equity Protection

See [Equity Protection — How It Works](#equity-protection--how-it-works) for the engine logic.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/protection/config` | 🔐 | Current limits + intervals |
| PUT/POST | `/protection/config` | 🔐 | Update config (validated; persisted atomically) |
| POST | `/protection/enable` | 🔐 | Start the heartbeat thread |
| POST | `/protection/disable` | 🔐 | Stop the heartbeat thread |
| GET | `/protection/status` | 🔐 | Current account drawdown, blocked status, peak equity, etc. |
| GET | `/protection/accounts` | 🔐 | Same for **all** known accounts |
| POST | `/protection/reset_block` | 🔐 | Manually unblock an account |
| POST | `/protection/toggle_verbose` | 🔐 | Toggle verbose logging |
| POST | `/protection/close/all` | 🔐 | Manual full liquidation |
| POST | `/protection/close/profitable` | 🔐 | Close winners |
| POST | `/protection/close/losing` | 🔐 | Close losers |
| POST | `/protection/close/symbol` | 🔐 | Close one symbol |

### WebSocket Management

REST helpers around the SocketIO server.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/ws/status` | 🔐 | Connected client count + subscriptions |
| GET | `/ws/info` | — | Self-documenting protocol description |
| GET | `/ws/clients` | 🔐 | List session IDs |
| GET | `/ws/subscriptions` | 🔐 | Per-client subscription map |
| POST | `/ws/broadcast/tick` | 🔐 | Manually push a tick (debug) |
| POST | `/ws/broadcast/position` | 🔐 | Manually push a position update |
| POST | `/ws/broadcast/order` | 🔐 | Manually push an order update |
| POST | `/ws/subscribe` | 🔐 | Returns instructions; real subscriptions go over the WS event |

### Metrics & Diagnostics

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/metrics` | 🔐 | Process and request metrics |
| GET | `/metrics/health` | 🔐 | Detailed health (vs the simple `/health`) |
| POST | `/metrics/reset` | 🔐 | Reset counters |
| GET | `/last_error` | 🔐 | Last MT5 error from `mt5.last_error()` |

---

## WebSocket Protocol

Connect over Socket.IO (same port as REST):

```js
import { io } from "socket.io-client";

const ws = io("http://localhost:5001", {
  transports: ["websocket"],
  // If MT5_API_KEY is set, pass it via auth handshake or extra headers:
  extraHeaders: { "X-API-Key": process.env.MT5_API_KEY },
});

ws.on("connect",    () => console.log("connected"));
ws.on("disconnect", () => console.log("disconnected"));

// Subscribe to whatever you want — fields are independent.
ws.emit("subscribe", {
  symbols:  ["EURUSD", "GBPUSD"],
  positions: true,
  orders:    true,
  account:   true
});

ws.on("tick",          d => /* {symbol, bid, ask, spread, volume, time} */);
ws.on("position_update", d => /* MT5 position dict */);
ws.on("order_update",    d => /* MT5 order dict */);
ws.on("account_update",  d => /* {login, balance, equity, margin, margin_free, margin_level, profit, currency, time} */);

// Equity-protection events
ws.on("protection_alert",   d => /* {account_number, reason, message, timestamp} */);
ws.on("equity_update",      d => /* live drawdown info */);
ws.on("protection_status",  d => /* {enabled, timestamp} */);
ws.on("account_blocked",    d => /* {account_number, reason, timestamp} */);
ws.on("account_unblocked",  d => /* {account_number, timestamp} */);
ws.on("connection_status",  d => /* {connected:true/false} */);

// Unsubscribe (fields independent)
ws.emit("unsubscribe", { symbols: ["GBPUSD"] });
```

### Stream cadence

| Stream | Driven by | Default rate |
|---|---|---|
| `tick`, `account_update` | `tick_stream_worker` | `ws_update_interval` (default 2.0s) |
| `equity_update`, protection events | Equity-protection heartbeat | `heartbeat_interval` (default 1.0s) |

The tick worker skips polling MT5 entirely when no client is subscribed — costs nothing at idle.

### Caps

- `MAX_WS_CLIENTS` connections (default 200) — additional handshakes are refused
- `MAX_WS_SYMBOLS_PER_CLIENT` (default 50) — extra symbols are silently dropped with an `error` event

---

## Equity Protection — How It Works

The protection engine is a background thread (`heartbeat_thread`) inside the API process. Every `heartbeat_interval` seconds it:

1. Reads `mt5.account_info()` (always fresh — never cached)
2. Computes drawdown according to `protection_mode`
3. If a limit is breached:
   - Calls `block_trading(account_number, reason)` → sets a flag, emits `account_blocked` over WS
   - If `action == close_all|close_losing|close_profitable`, runs the matching liquidation
   - If `action == notify_only`, just emits the alert
4. While `trading_blocked` is true, `POST /order` and `POST /limit_order` return `403`

### Configuration (`protection_config/protection_config.json`)

```json
{
  "max_daily_loss_pct":     3.0,        // % of daily starting equity/balance
  "max_total_drawdown_pct": 8.0,        // % from historical peak
  "max_daily_loss_abs":     0.0,        // absolute $ — 0 disables
  "max_total_drawdown_abs": 0.0,
  "min_margin_level_pct":  65.0,        // close if margin level drops below
  "protection_mode": "balance",         // "equity" or "balance"
  "action":          "close_all",       // close_all|close_losing|close_profitable|notify_only
  "heartbeat_interval":  1.0,           // seconds between checks
  "order_check_interval":1.0,
  "ws_update_interval":  2.0,
  "auto_reset_daily":    false,         // CAREFUL: true unblocks at midnight
  "verbose_logging":     true,
  "enabled":             true
}
```

### Modes

- **`equity`** — daily drawdown = `(daily_starting_equity − current_equity) / daily_starting_equity`; total drawdown = drawdown from historical peak equity
- **`balance`** — same but uses balance as the reference (current equity vs starting balance, peak balance for total)

### Persisted state (`protection_config/equity_history.json`)

Atomically written. Stores per-account: peak equity/balance, daily start, blocked accounts, notification reasons. Survives restarts so a tripped account stays blocked even if you redeploy.

### Manual unblock

```bash
curl -X POST http://localhost:5001/protection/reset_block \
  -H "X-API-Key: $MT5_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"account_number":"12345678"}'
```

### Race-free order block

The `@require_trading_not_blocked` decorator holds the protection lock for the duration of the order-send so the heartbeat cannot flip the block state mid-flight, and refuses orders while a liquidation is in progress (returns `409`).

---

## Performance & Caching

The Linux ↔ Wine MT5 IPC bridge adds ~2-5ms per call. Several optimizations reduce that:

| Optimization | Impact |
|---|---|
| **TTL cache** for `account_info` and `symbol_info_tick` (`utils/mt5_cache.py`) | Multiple readers within the TTL share a single Wine call. Default 100ms |
| **Cache bypassed** in equity protection and order placement | Risk-critical paths always read fresh |
| **WS tick worker skips polling** when no subscribers | Zero cost at idle |
| **WS broadcast collects targets under lock, emits outside** | A slow client can't stall ticks for everyone |
| **orjson** for JSON serialization | 3–5× faster than stdlib `json`. Falls back automatically if not installed |
| **eventlet** WSGI | Production-grade WS handling, scales to ~hundreds of clients on one process |
| **Logging middleware** skips JSON re-parse on 2xx responses | Faster successful responses |

> The MT5 Python library binds **one terminal per process**. Do not run multiple gunicorn workers — the second worker will lose its connection. Use `eventlet` (already configured) for concurrency instead.

---

## Logging

Logs go to stdout by default. To also write a rotating file:

```dotenv
LOG_FILE=/var/log/mt5/api.log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
LOG_LEVEL=INFO
```

The access log middleware adds:
- `X-Request-ID` response header
- per-request log entry: `request_id`, `method`, `path`, `status`, `duration_ms`, `remote_addr`, sanitized `query_params`
- `error_id` correlation on 4xx/5xx (skipped on 2xx for speed)
- sanitized: `password`, `api_key`, `secret`, `token`, `authorization` headers and query keys are redacted

---

## Graceful Shutdown

On `SIGTERM` / `SIGINT`:

1. Equity-protection thread receives `running = False`
2. Heartbeat and monitor threads are joined (3s timeout)
3. `mt5.shutdown()` is called
4. Atomic state write completes for `equity_history.json`

Run with `docker-compose down` (sends SIGTERM) — never `kill -9` unless you want truncated state.

---

## Production Checklist

| Item | Status |
|---|---|
| Eventlet WSGI (not Werkzeug dev server) | ✅ enabled by default |
| Atomic config + history writes | ✅ |
| Graceful shutdown | ✅ |
| MT5 reconnect with exponential backoff | ✅ (uses stored credentials) |
| Log rotation | ✅ via `LOG_FILE` |
| WebSocket connection caps | ✅ |
| Request size cap | ✅ 1 MB |
| API key auth | ⚠️ **Set `MT5_API_KEY` in any non-localhost deployment** |
| HTTPS / TLS | ⚠️ Terminate at reverse proxy (Traefik / nginx / Caddy) |
| Rate limiting | ⚠️ Add Flask-Limiter if exposed publicly |
| Pin `requirements.txt` | ⚠️ Run `pip-compile` for reproducible builds |
| Tests for protection state machine | ⚠️ Recommended |

---

## Troubleshooting

### `MT5 not connected at startup`

The bootstrap chain (env vars → persisted file → bare `initialize`) all failed.
- Confirm `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` are correct (server name is case-sensitive)
- Or open MT5 via VNC, log in manually, then call the API — it will attach to the running terminal
- Check `GET /mt5/login_status` for `last_error`

### `(-6) Authorization failed`

Wrong password or wrong server name. Open the MT5 Login dialog over VNC and copy the exact server string.

### Orders return `403 Trading blocked`

Equity protection has fired. `GET /protection/status` shows the reason. Manually unblock via `POST /protection/reset_block`, or address the cause and let `auto_reset_daily` clear it (if enabled).

### WebSocket disconnects after handshake

Origin not in `WS_ALLOWED_ORIGINS`. Add your frontend's exact origin (scheme + host + port).

### High CPU under Wine

`heartbeat_interval` set too low. Default is `1.0s` — anything below `0.5s` thrashes the IPC bridge. Tune in `protection_config.json`.

### Container won't shut down cleanly

Some thread is mid-write. The shutdown handler waits 3s per thread; persistent hangs usually mean the MT5 IPC is unresponsive. `docker-compose restart mt5` is safe — atomic writes guarantee no torn state.

---

## License

MIT — see `LICENSE.md`.
