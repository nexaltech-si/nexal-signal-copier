# MT5 MCP Server

MCP server that wraps **every** REST endpoint of the MetaTrader 5 Flask container.
Once connected to Claude (Desktop / Code), you can issue natural-language instructions
like *"buy 0.1 XAUUSD with SL at 3290"* or *"show me my equity protection status"* and
Claude will call the correct tool automatically.

---

## Tools reference (44 tools)

| Category | Tools |
|---|---|
| **Health / System** | `mt5_health`, `mt5_version`, `mt5_account_info`, `mt5_terminal_info`, `mt5_last_error` |
| **Session** | `mt5_login`, `mt5_logout`, `mt5_login_status` |
| **Symbols** | `mt5_get_symbols`, `mt5_search_symbols`, `mt5_symbol_info`, `mt5_symbol_tick`, `mt5_market_book` |
| **Market Data** | `mt5_fetch_ohlcv`, `mt5_fetch_ohlcv_range`, `mt5_fetch_ticks`, `mt5_fetch_ticks_range` |
| **Positions** | `mt5_positions_total`, `mt5_get_positions`, `mt5_get_pending_orders`, `mt5_close_position`, `mt5_close_partial`, `mt5_close_all_positions`, `mt5_close_profitable_positions`, `mt5_close_losing_positions`, `mt5_close_symbol_positions`, `mt5_modify_sl_tp` |
| **Orders** | `mt5_market_order`, `mt5_pending_order`, `mt5_cancel_order`, `mt5_modify_order`, `mt5_cancel_all_orders` |
| **History** | `mt5_history_deals`, `mt5_history_orders`, `mt5_deal_from_ticket`, `mt5_order_from_ticket`, `mt5_account_stats` |
| **Trade Lifecycle** | `mt5_trade_lifecycle`, `mt5_trade_status`, `mt5_batch_trade_status`, `mt5_trade_search` |
| **Seasonal** | `mt5_seasonal_analysis` |
| **Equity Protection** | `mt5_protection_status`, `mt5_protection_config`, `mt5_update_protection_config`, `mt5_protection_enable`, `mt5_protection_disable`, `mt5_reset_trading_block`, `mt5_protection_all_accounts`, `mt5_liquidate_all`, `mt5_liquidate_profitable`, `mt5_liquidate_losing`, `mt5_liquidate_symbol` |
| **Metrics / WS** | `mt5_metrics`, `mt5_metrics_health`, `mt5_websocket_status` |

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment variables

| Variable | Default | Description |
|---|---|---|
| `MT5_API_URL` | `http://localhost:5002` | Base URL of your MT5 container (as mapped in docker-compose) |
| `MT5_API_KEY` | _(empty)_ | Value of `MT5_API_KEY` set in the container's `.env` |

### 3. Claude Desktop — add to `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mt5": {
      "command": "python",
      "args": ["/absolute/path/to/mt5_mcp.py"],
      "env": {
        "MT5_API_URL": "http://localhost:5002",
        "MT5_API_KEY": "your_secret_key_here"
      }
    }
  }
}
```

### 4. Claude Code (CLI)

```bash
MT5_API_URL=http://localhost:5002 MT5_API_KEY=your_key claude mcp add mt5 -- python /path/to/mt5_mcp.py
```

Or add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "mt5": {
      "command": "python",
      "args": ["mt5_mcp.py"],
      "env": {
        "MT5_API_URL": "http://localhost:5002",
        "MT5_API_KEY": "your_key"
      }
    }
  }
}
```

### 5. Test with MCP Inspector

```bash
MT5_API_URL=http://localhost:5002 MT5_API_KEY=your_key npx @modelcontextprotocol/inspector python mt5_mcp.py
```

---

## Example prompts once connected

```
Show me my account balance and current equity.

What is the current bid/ask for XAUUSD?

Buy 0.05 XAUUSD at market with SL at 3280 and TP at 3360.

What are all my open positions?

Close my losing XAUUSD positions.

Show me my trade statistics for May 2026.

Set my daily drawdown limit to 2.5% and action to notify_only.

What is my current equity protection status?

Give me the last 200 H4 candles for XAUUSD.

Show me seasonal win probability for XAUUSD over the last 20 years.
```

---

## Architecture note

The MCP server is a **thin async proxy** — it validates inputs with Pydantic,
builds the correct HTTP request, and returns the raw JSON from the Flask container.
No trading logic lives here; everything is in the MT5 container.

The server uses `stdio` transport (default), meaning Claude spawns it as a subprocess.
If you want to run it as a persistent HTTP MCP server instead, change the last line to:

```python
mcp.run(transport="streamable_http", port=8001)
```
