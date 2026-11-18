# MetaTrader5 REST API Documentation

## Overview
This API provides access to MetaTrader 5 trading operations including order management, position monitoring, historical data retrieval, market data access, and real-time WebSocket updates.

## Authentication
All endpoints require an API key passed in the `X-API-Key` header. Set the `MT5_API_KEY` environment variable to configure the required key.

```bash
curl -H "X-API-Key: your-api-key" http://localhost:5000/account_info
```

## Quick Start

### 1. Check Health
```bash
curl http://localhost:5000/health
```

### 2. Get Account Info
```bash
curl -H "X-API-Key: your-key" http://localhost:5000/account_info
```

### 3. Place Market Order
```bash
curl -X POST http://localhost:5000/order \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "EURUSD",
    "volume": 0.1,
    "type": "BUY",
    "sl": 1.0800,
    "tp": 1.0900
  }'
```

## API Categories

### 🏥 Health & System
- `GET /health` - Health check
- `GET /version` - MT5 version
- `GET /terminal_info` - Terminal information
- `GET /account_info` - Account details

### 📊 Symbols & Market Info
- `GET /symbols` - List all symbols
- `GET /symbols/search?group=*USD*` - Search symbols
- `GET /symbol_info/<symbol>` - Symbol specification
- `GET /symbol_info_tick/<symbol>` - Latest tick
- `GET /market_book/<symbol>` - Market depth (DOM)

### 📈 Market Data
- `GET /fetch_data_pos` - OHLCV from current position
- `GET /fetch_data_range` - OHLCV in date range
- `GET /fetch_ticks` - Tick data from datetime
- `GET /fetch_ticks_range` - Tick data in range

### 📝 Orders
- `POST /order` - Market order (BUY/SELL)
- `POST /limit_order` - Pending order (LIMIT/STOP)
- `POST /cancel_order` - Cancel pending order
- `POST /modify_order` - Modify pending order
- `POST /close_all_orders` - Close all pending orders (with optional filtering)

### 💼 Positions
- `GET /positions_total` - Count open positions
- `GET /get_positions` - List all positions
- `GET /get_orders` - List pending orders
- `POST /close_position` - Close position
- `POST /close_partial` - Partially close position
- `POST /close_all_positions` - Close all positions
- `POST /modify_sl_tp` - Modify SL/TP

### 📜 History & Statistics
- `GET /history_deals_get` - Historical deals
- `GET /history_orders_get` - Historical orders
- `GET /get_deal_from_ticket` - Deal summary by ticket
- `GET /get_order_from_ticket` - Order by ticket
- `GET /account_stats` - Trade statistics

### 🔄 Trade Lifecycle
- `GET /trade_lifecycle` - Complete trade lifecycle
- `GET /trade_status` - Quick status check
- `POST /trade_batch_status` - Batch status check
- `GET /trade_search` - Search trades

### 📅 Seasonal Analysis
- `GET /seasonal/<symbol>` - Monthly seasonal patterns

### ⚠️ Error Handling
- `GET /last_error` - Last MT5 error

## Timeframes

Supported timeframes: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M10`, `M12`, `M15`, `M20`, `M30`, `H1`, `H2`, `H3`, `H4`, `H6`, `H8`, `H12`, `D1`, `W1`, `MN1`

## Order Types

### Market Orders
- `BUY` - Buy at market
- `SELL` - Sell at market

### Pending Orders
- `BUY_LIMIT` - Buy when price drops to level
- `SELL_LIMIT` - Sell when price rises to level
- `BUY_STOP` - Buy when price rises to level
- `SELL_STOP` - Sell when price drops to level
- `BUY_STOP_LIMIT` - Buy stop with limit price
- `SELL_STOP_LIMIT` - Sell stop with limit price

## Trade Status Values

- `PENDING` - Limit/stop order not yet filled
- `RUNNING` - Position is open
- `CLOSED_PROFIT` - Position closed with profit
- `CLOSED_LOSS` - Position closed with loss
- `CLOSED_BREAKEVEN` - Position closed at breakeven
- `CANCELED` - Order was canceled
- `EXPIRED` - Order expired
- `REJECTED` - Order was rejected
- `UNKNOWN` - Cannot determine status

## Examples

### Get OHLCV Data
```bash
# Last 100 M15 bars
curl "http://localhost:5000/fetch_data_pos?symbol=EURUSD&timeframe=M15&num_bars=100" \
  -H "X-API-Key: your-key"

# Date range
curl "http://localhost:5000/fetch_data_range?symbol=EURUSD&timeframe=H1&start=2024-01-01T00:00:00Z&end=2024-01-31T23:59:59Z" \
  -H "X-API-Key: your-key"
```

### Place Pending Order
```bash
curl -X POST http://localhost:5000/limit_order \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "GBPUSD",
    "volume": 0.1,
    "type": "BUY_LIMIT",
    "price": 1.2500,
    "sl": 1.2450,
    "tp": 1.2600,
    "magic": 12345,
    "comment": "My limit order"
  }'
```

### Modify Position SL/TP
```bash
curl -X POST http://localhost:5000/modify_sl_tp \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "position": 123456789,
    "sl": 1.0850,
    "tp": 1.0950
  }'
```

### Get Trade Lifecycle
```bash
curl "http://localhost:5000/trade_lifecycle?ticket=123456789&days_back=30" \
  -H "X-API-Key: your-key"
```

### Get Account Statistics
```bash
curl "http://localhost:5000/account_stats?from_date=2024-01-01T00:00:00Z&to_date=2024-12-31T23:59:59Z" \
  -H "X-API-Key: your-key"
```

### Seasonal Analysis
```bash
curl "http://localhost:5000/seasonal/EURUSD?years=20" \
  -H "X-API-Key: your-key"
```

### Batch Trade Status
```bash
curl -X POST http://localhost:5000/trade_batch_status \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "tickets": [123456, 123457, 123458]
  }'
```

## Response Formats

### Success Response
```json
{
  "message": "Order executed",
  "result": {
    "retcode": 10009,
    "deal": 123456789,
    "order": 123456788,
    "volume": 0.1,
    "price": 1.0850,
    "comment": "Request completed"
  }
}
```

### Error Response
```json
{
  "error": "Invalid parameters",
  "mt5_error": "Invalid volume",
  "retcode": 10014
}
```

## Error Codes

### MT5 Return Codes (retcode)

The API returns MT5 return codes in the `retcode` field of error responses. These are the exact MT5 trade return codes:

**Success Codes:**
- `10008` - TRADE_RETCODE_PLACED - Order placed
- `10009` - TRADE_RETCODE_DONE - Request completed

**Rejection Codes:**
- `10004` - TRADE_RETCODE_REQUOTE - Requote
- `10006` - TRADE_RETCODE_REJECT - Request rejected
- `10007` - TRADE_RETCODE_CANCEL - Request canceled by trader
- `10010` - TRADE_RETCODE_DONE_PARTIAL - Only part of the request was completed
- `10011` - TRADE_RETCODE_ERROR - Request processing error
- `10012` - TRADE_RETCODE_TIMEOUT - Request canceled by timeout
- `10013` - TRADE_RETCODE_INVALID - Invalid request

**Validation Errors:**
- `10014` - TRADE_RETCODE_INVALID_VOLUME - Invalid volume
- `10015` - TRADE_RETCODE_INVALID_PRICE - Invalid price
- `10016` - TRADE_RETCODE_INVALID_STOPS - Invalid stops
- `10017` - TRADE_RETCODE_TRADE_DISABLED - Trade is disabled
- `10020` - TRADE_RETCODE_NO_MONEY - Insufficient funds
- `10021` - TRADE_RETCODE_PRICE_OFF - No quotes available

**Market Conditions:**
- `10018` - TRADE_RETCODE_MARKET_CLOSED - Market is closed
- `10019` - TRADE_RETCODE_NO_MONEY - Insufficient funds
- `10022` - TRADE_RETCODE_INVALID_EXPIRATION - Invalid expiration date
- `10023` - TRADE_RETCODE_ORDER_CHANGED - Order state changed
- `10024` - TRADE_RETCODE_TOO_MANY_REQUESTS - Too many requests
- `10025` - TRADE_RETCODE_NO_CHANGES - No changes in request
- `10026` - TRADE_RETCODE_SERVER_DISABLES_AT - Autotrading disabled by server
- `10027` - TRADE_RETCODE_CLIENT_DISABLES_AT - Autotrading disabled by client
- `10028` - TRADE_RETCODE_LOCKED - Request locked
- `10029` - TRADE_RETCODE_FROZEN - Order/position frozen
- `10030` - TRADE_RETCODE_ONLY_REAL - Live accounts only
- `10031` - TRADE_RETCODE_LIMIT_POSITIONS - Open position limit reached
- `10032` - TRADE_RETCODE_LIMIT_ORDERS - Pending order limit reached
- `10033` - TRADE_RETCODE_LIMIT_VOLUME - Volume limit reached
- `10034` - TRADE_RETCODE_INVALID_ORDER - Incorrect order type
- `10035` - TRADE_RETCODE_CONNECTION - No connection with trade server
- `10036` - TRADE_RETCODE_POSITION_CLOSED - Position already closed
- `10037` - TRADE_RETCODE_INVALID_CLOSE_VOLUME - Close volume exceeds position
- `10038` - TRADE_RETCODE_CLOSE_ORDER_EXIST - Close order already exists
- `10039` - TRADE_RETCODE_REJECT_CANCEL - Activation rejected, order canceled
- `10040` - TRADE_RETCODE_LONG_ONLY - Only long positions allowed
- `10041` - TRADE_RETCODE_SHORT_ONLY - Only short positions allowed
- `10042` - TRADE_RETCODE_CLOSE_ONLY - Only position closing allowed
- `10043` - TRADE_RETCODE_FIFO_CLOSE - FIFO close rule enforced
- `10044` - TRADE_RETCODE_INVALID_FILL - Invalid filling type

**Custom Error IDs:**
Each error response includes a unique `error_id` for tracking and debugging. This is a UUID that can be used to correlate errors with logs.

## Best Practices

1. **Always check health** before trading operations
2. **Use magic numbers** to identify your orders/positions
3. **Set SL/TP** on every order for risk management
4. **Handle errors gracefully** - check retcode and mt5_error
5. **Use appropriate timeframes** for your strategy
6. **Monitor account stats** regularly
7. **Test on demo** before live trading
8. **Use trade lifecycle** endpoints for comprehensive tracking

## Rate Limiting

No built-in rate limiting. Implement client-side throttling to avoid overwhelming MT5 terminal.

## WebSocket Support

Real-time WebSocket support using Flask-SocketIO for live price updates, position changes, and order status.

### Connection
```javascript
const socket = io('http://localhost:5000');
```

### Events

#### Connect
```javascript
socket.on('connect', () => {
  console.log('Connected');
});
```

#### Subscribe to Updates
```javascript
socket.emit('subscribe', {
  symbols: ['EURUSD', 'GBPUSD'],
  positions: true,
  orders: true
});
```

#### Receive Tick Updates
```javascript
socket.on('tick', (data) => {
  console.log('Price update:', data);
  // {symbol, bid, ask, spread, time}
});
```

#### Receive Position Updates
```javascript
socket.on('position_update', (data) => {
  console.log('Position update:', data);
});
```

#### Receive Order Updates
```javascript
socket.on('order_update', (data) => {
  console.log('Order update:', data);
});
```

#### Unsubscribe
```javascript
socket.emit('unsubscribe', {
  symbols: ['EURUSD'],
  positions: true
});
```

### Check Status
```bash
curl -H "X-API-Key: your-api-key" http://localhost:5000/ws/status
```

### Requirements
```bash
pip install flask-socketio
```

## Security

- Set `MT5_API_KEY` environment variable to enable authentication
- Use HTTPS in production
- Never expose API keys in client-side code
- Implement IP whitelisting if needed
- Monitor for unusual trading activity

## Troubleshooting

### MT5 Not Connected
```json
{"status": "healthy", "mt5_connected": false}
```
**Solution:** Ensure MT5 terminal is running and logged in

### Order Failed
```json
{"error": "Order failed: Invalid stops", "retcode": 10016}
```
**Solution:** Check SL/TP levels are valid for the symbol

### No Data Returned
```json
{"error": "No data returned"}
```
**Solution:** Verify symbol name, timeframe, and date range

## Support

For issues or questions:
1. Check `/last_error` endpoint for MT5 errors
2. Review logs in MT5 terminal
3. Verify account permissions and trading hours
4. Check symbol trading sessions

## Version

API Version: 2.0.0  
MT5 API: Check `/version` endpoint
