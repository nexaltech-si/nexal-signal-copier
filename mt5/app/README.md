# MT5 REST API

A production-ready Flask REST API wrapping the MetaTrader5 Python library.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set MT5_API_KEY, MT5_API_PORT
python app.py
```

Interactive docs: http://localhost:5000/apidocs/

## Authentication

Set `MT5_API_KEY` in `.env`. Pass the key as:
```
X-API-Key: your_secret_key_here
```
Leave `MT5_API_KEY` blank to disable auth (development only).

---

## Endpoints

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Liveness check (no auth required) |
| GET | /account_info | Balance, equity, margin, leverage |
| GET | /terminal_info | Build, path, connection status |
| GET | /version | MT5 terminal version |

### Symbol
| Method | Path | Description |
|--------|------|-------------|
| GET | /symbols | All Market Watch symbols |
| GET | /symbols/search?group=*USD* | Filter symbols by group pattern |
| GET | /symbol_info/<symbol> | Full symbol specification |
| GET | /symbol_info_tick/<symbol> | Latest bid/ask tick |
| GET | /market_book/<symbol> | Depth of Market (DOM) |

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | /fetch_data_pos | OHLCV bars from current position |
| GET | /fetch_data_range | OHLCV bars in date range |
| GET | /fetch_ticks | Tick data from datetime |
| GET | /fetch_ticks_range | Tick data in date range |

**Timeframes:** M1 M2 M3 M4 M5 M6 M10 M12 M15 M20 M30 H1 H2 H3 H4 H6 H8 H12 D1 W1 MN1

**Tick flags:** 1=INFO, 2=TRADE, 3=ALL

### Orders
| Method | Path | Description |
|--------|------|-------------|
| POST | /order | Market BUY or SELL |
| POST | /limit_order | All pending types (BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, BUY_STOP_LIMIT, SELL_STOP_LIMIT) |
| POST | /cancel_order | Cancel a pending order |
| POST | /modify_order | Modify pending order price/SL/TP |

#### Market Order Body
```json
{
  "symbol": "EURUSD",
  "volume": 0.1,
  "type": "BUY",
  "sl": 1.08000,
  "tp": 1.09500,
  "deviation": 20,
  "magic": 12345,
  "comment": "my bot",
  "type_filling": "ORDER_FILLING_IOC"
}
```

#### Pending Order Body
```json
{
  "symbol": "EURUSD",
  "volume": 0.1,
  "type": "BUY_LIMIT",
  "price": 1.08000,
  "sl": 1.07500,
  "tp": 1.09000,
  "expiration": "2026-01-01T00:00:00Z"
}
```

### Positions
| Method | Path | Description |
|--------|------|-------------|
| GET | /positions_total | Count of open positions |
| GET | /get_positions | All open positions (optional ?magic=) |
| GET | /get_orders | All pending orders (optional ?magic=) |
| POST | /close_position | Close a specific position |
| POST | /close_partial | Partial close (specify volume) |
| POST | /close_all_positions | Close all / filtered positions |
| POST | /modify_sl_tp | Update SL/TP on open position |

#### Close Position Body
```json
{
  "position": { "ticket": 123456, "type": 0, "symbol": "EURUSD", "volume": 0.1 }
}
```

#### Partial Close Body
```json
{
  "position": { "ticket": 123456, "type": 0, "symbol": "EURUSD", "volume": 0.1 },
  "volume": 0.05
}
```

#### Modify SL/TP Body
```json
{ "position": 123456, "sl": 1.08000, "tp": 1.10000 }
```

### History
| Method | Path | Description |
|--------|------|-------------|
| GET | /history_deals_get | Deals in date range (optional ?position=) |
| GET | /history_orders_get | Orders by ticket or date range |
| GET | /get_deal_from_ticket | Summary for a position ticket |
| GET | /get_order_from_ticket | Order record by ticket |
| GET | /account_stats | Win rate, P&L stats, profit factor |

#### Account Stats Query
```
GET /account_stats?from_date=2025-01-01T00:00:00Z&to_date=2026-01-01T00:00:00Z
```

### Error
| Method | Path | Description |
|--------|------|-------------|
| GET | /last_error | Last MT5 error code + message |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| MT5_API_PORT | 5000 | Port to listen on |
| MT5_API_KEY | (blank) | API key — blank disables auth |
| LOG_LEVEL | INFO | DEBUG / INFO / WARNING / ERROR |