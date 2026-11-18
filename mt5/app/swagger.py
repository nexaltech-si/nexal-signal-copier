swagger_config = {
    "swagger": "2.0",
    "schemes": ["http"],
    "host": "localhost:5002",
    "info": {
        "title": "MetaTrader5 REST API",
        "description": (
            "Comprehensive REST API for MetaTrader5 trading platform.\n\n"
            "**Features:**\n"
            "- Market & Pending Orders (BUY, SELL, LIMIT, STOP)\n"
            "- Position Management (Open, Close, Modify SL/TP)\n"
            "- OHLCV & Tick Data (Historical & Real-time)\n"
            "- Trade Lifecycle Tracking (Order → Deal → Position → History)\n"
            "- Account Statistics & Performance Metrics\n"
            "- Symbol Search & Market Depth (DOM)\n"
            "- Seasonal Analysis & Historical Patterns\n\n"
            "**Authentication:**\n"
            "Most endpoints require authentication via `X-API-Key` header when MT5_API_KEY env var is set.\n\n"
            "**Base URL:** `http://localhost:5000` (configurable via MT5_API_PORT)\n\n"
            "**Timeframes:** M1, M2, M3, M4, M5, M6, M10, M12, M15, M20, M30, H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1\n\n"
            "**Order Types:** BUY, SELL, BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP, BUY_STOP_LIMIT, SELL_STOP_LIMIT"
        ),
        "version": "2.0.0",
        "contact": {
            "name": "MT5 API Support",
            "email": "support@example.com"
        },
        "license": {
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT"
        }
    },
    "basePath": "/",
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "securityDefinitions": {
        "ApiKeyAuth": {
            "type": "apiKey",
            "name": "X-API-Key",
            "in": "header",
            "description": "API Key for authentication. Set MT5_API_KEY environment variable to enable."
        }
    },
    "security": [{"ApiKeyAuth": []}],
    "tags": [
        {"name": "Health", "description": "Health check and status"},
        {"name": "MT5 Session", "description": "Login/logout to a broker server"},
        {"name": "Symbols", "description": "Symbol information and market data"},
        {"name": "Orders", "description": "Order management"},
        {"name": "Positions", "description": "Position management and modification"},
        {"name": "History", "description": "Historical deals, orders, and statistics"},
        {"name": "Trade Lifecycle", "description": "Complete trade tracking and status"},
        {"name": "Seasonal", "description": "Seasonal analysis and patterns"},
        {"name": "WebSocket", "description": "Real-time WebSocket connections and events"},
        {"name": "Metrics", "description": "API metrics and monitoring"},
        {"name": "Protection", "description": "Equity protection and risk management"},
        {"name": "Error", "description": "MT5 error information"}
    ],
    "definitions": {
        "Error": {
            "type": "object",
            "properties": {
                "error_id": {"type": "string", "description": "Unique error identifier for tracking", "example": "550e8400-e29b-41d4-a716-446655440000"},
                "error": {"type": "string", "description": "Error message"},
                "error_type": {"type": "string", "description": "Type of error (e.g., ValidationError, OrderError, MT5ConnectionError)"},
                "mt5_error": {"type": "string", "description": "MT5 error description from TRADE_RETCODE_DESCRIPTION"},
                "retcode": {"type": "integer", "description": "MT5 return code (e.g., 10014 for invalid volume)"},
                "suggestion": {"type": "string", "description": "Suggested action to resolve the error"},
                "endpoint": {"type": "string", "description": "Endpoint where the error occurred"},
                "request_context": {"type": "object", "description": "Request parameters for debugging"},
                "timestamp": {"type": "string", "format": "date-time", "description": "ISO timestamp when error occurred"}
            }
        },
        "HealthStatus": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "example": "healthy"},
                "mt5_connected": {"type": "boolean"},
                "mt5_initialized": {"type": "boolean"}
            }
        },
        "AccountInfo": {
            "type": "object",
            "properties": {
                "login": {"type": "integer"},
                "server": {"type": "string"},
                "currency": {"type": "string"},
                "leverage": {"type": "integer"},
                "balance": {"type": "number"},
                "credit": {"type": "number"},
                "profit": {"type": "number"},
                "equity": {"type": "number"},
                "margin": {"type": "number"},
                "margin_free": {"type": "number"},
                "margin_level": {"type": "number"},
                "margin_so_call": {"type": "number"},
                "margin_so_so": {"type": "number"},
                "trade_allowed": {"type": "boolean"},
                "trade_expert": {"type": "boolean"},
                "limit_orders": {"type": "integer"}
            }
        },
        "OHLCVBar": {
            "type": "object",
            "properties": {
                "time": {"type": "string", "format": "date-time"},
                "open": {"type": "number"},
                "high": {"type": "number"},
                "low": {"type": "number"},
                "close": {"type": "number"},
                "tick_volume": {"type": "integer"},
                "spread": {"type": "integer"},
                "real_volume": {"type": "integer"}
            }
        },
        "Position": {
            "type": "object",
            "properties": {
                "ticket": {"type": "integer"},
                "time": {"type": "string", "format": "date-time"},
                "type": {"type": "string", "enum": ["BUY", "SELL"]},
                "magic": {"type": "integer"},
                "volume": {"type": "number"},
                "price_open": {"type": "number"},
                "sl": {"type": "number"},
                "tp": {"type": "number"},
                "price_current": {"type": "number"},
                "swap": {"type": "number"},
                "profit": {"type": "number"},
                "symbol": {"type": "string"},
                "comment": {"type": "string"}
            }
        },
        "OrderRequest": {
            "type": "object",
            "required": ["symbol", "volume", "type"],
            "properties": {
                "symbol": {"type": "string", "minLength": 1, "maxLength": 32, "example": "EURUSD"},
                "volume": {"type": "number", "minimum": 0.01, "maximum": 100, "example": 0.1},
                "type": {"type": "string", "enum": ["BUY", "SELL", "0", "1"]},
                "sl": {"type": "number", "minimum": 0, "description": "Stop Loss price"},
                "tp": {"type": "number", "minimum": 0, "description": "Take Profit price"},
                "deviation": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 20},
                "magic": {"type": "integer", "minimum": 0, "maximum": 2147483647, "default": 0},
                "comment": {"type": "string", "maxLength": 128},
                "type_filling": {"type": "string", "enum": ["ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"]}
            }
        },
        "PendingOrderRequest": {
            "type": "object",
            "required": ["symbol", "volume", "type", "price"],
            "properties": {
                "symbol": {"type": "string", "minLength": 1, "maxLength": 32, "example": "EURUSD"},
                "volume": {"type": "number", "minimum": 0.01, "maximum": 100, "example": 0.1},
                "type": {"type": "string", "enum": ["BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "BUY_STOP_LIMIT", "SELL_STOP_LIMIT"]},
                "price": {"type": "number", "minimum": 0, "description": "Order trigger price"},
                "stoplimit_price": {"type": "number", "minimum": 0, "description": "Required for STOP_LIMIT orders"},
                "sl": {"type": "number", "minimum": 0},
                "tp": {"type": "number", "minimum": 0},
                "deviation": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 20},
                "magic": {"type": "integer", "minimum": 0, "maximum": 2147483647, "default": 0},
                "comment": {"type": "string", "maxLength": 128},
                "expiration": {"type": "string", "format": "date-time", "description": "ISO 8601 format"},
                "type_filling": {"type": "string", "enum": ["ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"]}
            }
        },
        "ModifyOrderRequest": {
            "type": "object",
            "required": ["ticket"],
            "properties": {
                "ticket": {"type": "integer", "minimum": 1},
                "price": {"type": "number", "minimum": 0},
                "sl": {"type": "number", "minimum": 0},
                "tp": {"type": "number", "minimum": 0},
                "stoplimit_price": {"type": "number", "minimum": 0},
                "expiration": {"type": "string", "format": "date-time"}
            }
        },
        "ModifySLTPRequest": {
            "type": "object",
            "required": ["position"],
            "properties": {
                "position": {"type": "integer", "minimum": 1, "description": "Position ticket number"},
                "sl": {"type": "number", "minimum": 0, "description": "New Stop Loss price"},
                "tp": {"type": "number", "minimum": 0, "description": "New Take Profit price"}
            }
        },
        "TradeResult": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "result": {
                    "type": "object",
                    "properties": {
                        "retcode": {"type": "integer"},
                        "deal": {"type": "integer"},
                        "order": {"type": "integer"},
                        "volume": {"type": "number"},
                        "price": {"type": "number"},
                        "comment": {"type": "string"}
                    }
                }
            }
        },
        "TradeLifecycle": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["PENDING", "RUNNING", "CLOSED_PROFIT", "CLOSED_LOSS", "CLOSED_BREAKEVEN", "CANCELED", "EXPIRED", "REJECTED", "UNKNOWN"]},
                "pending_order": {"type": "object"},
                "position": {"$ref": "#/definitions/Position"},
                "order_history": {"type": "object"},
                "deals": {"type": "array", "items": {"type": "object"}},
                "summary": {
                    "type": "object",
                    "properties": {
                        "ticket": {"type": "integer"},
                        "status": {"type": "string"},
                        "total_profit": {"type": "number"},
                        "total_commission": {"type": "number"},
                        "total_swap": {"type": "number"},
                        "net_pnl": {"type": "number"},
                        "entry_price": {"type": "number"},
                        "exit_price": {"type": "number"}
                    }
                }
            }
        },
        "SeasonalAnalysis": {
            "type": "object",
            "properties": {
                "pair": {"type": "string"},
                "years": {"type": "array", "items": {"type": "integer"}},
                "months": {"type": "array", "items": {"type": "string"}},
                "probability": {"type": "object", "description": "Win probability per month"},
                "avg_return": {"type": "object", "description": "Average return per month"},
                "returns": {"type": "object", "description": "Year-by-year monthly returns"}
            }
        },
        "TerminalInfo": {
            "type": "object",
            "properties": {
                "community_account": {"type": "boolean"},
                "community_connection": {"type": "boolean"},
                "connected": {"type": "boolean", "description": "Connected to broker"},
                "dlls_allowed": {"type": "boolean"},
                "trade_allowed": {"type": "boolean"},
                "tradeapi_disabled": {"type": "boolean"},
                "email_enabled": {"type": "boolean"},
                "ftp_enabled": {"type": "boolean"},
                "notifications_enabled": {"type": "boolean"},
                "mqid": {"type": "boolean"},
                "build": {"type": "integer"},
                "maxbars": {"type": "integer"},
                "codepage": {"type": "integer"},
                "ping_last": {"type": "integer", "description": "Last ping (microseconds)"},
                "community_balance": {"type": "number"},
                "retransmission": {"type": "number"},
                "company": {"type": "string"},
                "name": {"type": "string"},
                "language": {"type": "string"},
                "path": {"type": "string"},
                "data_path": {"type": "string"},
                "commondata_path": {"type": "string"}
            }
        },
        "SymbolInfo": {
            "type": "object",
            "description": "Full MT5 SymbolInfo record",
            "properties": {
                "name": {"type": "string", "example": "EURUSD"},
                "description": {"type": "string"},
                "currency_base": {"type": "string"},
                "currency_profit": {"type": "string"},
                "currency_margin": {"type": "string"},
                "digits": {"type": "integer", "description": "Decimal precision"},
                "spread": {"type": "integer", "description": "Spread in points"},
                "spread_float": {"type": "boolean"},
                "trade_contract_size": {"type": "number", "example": 100000},
                "trade_tick_size": {"type": "number"},
                "trade_tick_value": {"type": "number"},
                "trade_stops_level": {"type": "integer"},
                "trade_freeze_level": {"type": "integer"},
                "volume_min": {"type": "number"},
                "volume_max": {"type": "number"},
                "volume_step": {"type": "number"},
                "volume_limit": {"type": "number"},
                "swap_long": {"type": "number"},
                "swap_short": {"type": "number"},
                "margin_initial": {"type": "number"},
                "margin_maintenance": {"type": "number"},
                "session_deals": {"type": "integer"},
                "session_buy_orders": {"type": "integer"},
                "session_sell_orders": {"type": "integer"},
                "visible": {"type": "boolean"},
                "select": {"type": "boolean"},
                "bid": {"type": "number"},
                "ask": {"type": "number"},
                "last": {"type": "number"},
                "time": {"type": "integer", "description": "Last quote time (Unix seconds)"},
                "filling_mode": {"type": "integer"},
                "order_mode": {"type": "integer"},
                "expiration_mode": {"type": "integer"},
                "trade_mode": {"type": "integer"},
                "trade_calc_mode": {"type": "integer"},
                "path": {"type": "string", "description": "Symbol category path"}
            }
        },
        "Tick": {
            "type": "object",
            "properties": {
                "time": {"type": "integer", "description": "Tick time (Unix seconds)"},
                "bid": {"type": "number"},
                "ask": {"type": "number"},
                "last": {"type": "number"},
                "volume": {"type": "integer"},
                "time_msc": {"type": "integer", "description": "Tick time in milliseconds"},
                "flags": {"type": "integer", "description": "Bit flags: TICK_FLAG_BID|ASK|LAST|VOLUME|BUY|SELL"},
                "volume_real": {"type": "number"}
            }
        },
        "MarketBookEntry": {
            "type": "object",
            "properties": {
                "type": {"type": "integer", "description": "1=BUY, 2=SELL"},
                "price": {"type": "number"},
                "volume": {"type": "number"},
                "volume_real": {"type": "number"}
            }
        },
        "Deal": {
            "type": "object",
            "description": "MT5 historical deal record",
            "properties": {
                "ticket": {"type": "integer", "description": "Deal ticket"},
                "order": {"type": "integer", "description": "Originating order ticket"},
                "position_id": {"type": "integer"},
                "time": {"type": "integer", "description": "Deal time (Unix seconds)"},
                "time_msc": {"type": "integer"},
                "type": {"type": "integer", "description": "Deal type: 0=BUY, 1=SELL, 2=BALANCE, …"},
                "entry": {"type": "integer", "description": "Entry direction: 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY"},
                "magic": {"type": "integer"},
                "reason": {"type": "integer"},
                "volume": {"type": "number"},
                "price": {"type": "number"},
                "commission": {"type": "number"},
                "swap": {"type": "number"},
                "profit": {"type": "number"},
                "fee": {"type": "number"},
                "symbol": {"type": "string"},
                "comment": {"type": "string"},
                "external_id": {"type": "string"}
            }
        },
        "HistoricalOrder": {
            "type": "object",
            "description": "MT5 historical order record",
            "properties": {
                "ticket": {"type": "integer"},
                "time_setup": {"type": "integer"},
                "time_setup_msc": {"type": "integer"},
                "time_done": {"type": "integer"},
                "time_done_msc": {"type": "integer"},
                "time_expiration": {"type": "integer"},
                "type": {"type": "integer", "description": "0=BUY, 1=SELL, 2=BUY_LIMIT, 3=SELL_LIMIT, 4=BUY_STOP, 5=SELL_STOP, …"},
                "type_filling": {"type": "integer"},
                "type_time": {"type": "integer"},
                "state": {"type": "integer", "description": "Order state (filled, canceled, rejected, expired, …)"},
                "magic": {"type": "integer"},
                "position_id": {"type": "integer"},
                "position_by_id": {"type": "integer"},
                "reason": {"type": "integer"},
                "volume_initial": {"type": "number"},
                "volume_current": {"type": "number"},
                "price_open": {"type": "number"},
                "price_current": {"type": "number"},
                "price_stoplimit": {"type": "number"},
                "sl": {"type": "number"},
                "tp": {"type": "number"},
                "symbol": {"type": "string"},
                "comment": {"type": "string"},
                "external_id": {"type": "string"}
            }
        },
        "DealSummary": {
            "type": "object",
            "description": "Aggregated P&L for all deals belonging to one position ticket",
            "properties": {
                "ticket": {"type": "integer", "description": "Position ticket"},
                "symbol": {"type": "string"},
                "type": {"type": "string", "enum": ["BUY", "SELL"]},
                "volume": {"type": "number"},
                "entry_price": {"type": "number"},
                "exit_price": {"type": "number"},
                "open_time": {"type": "string", "format": "date-time"},
                "close_time": {"type": "string", "format": "date-time"},
                "profit": {"type": "number"},
                "commission": {"type": "number"},
                "swap": {"type": "number"},
                "fee": {"type": "number"},
                "net_pnl": {"type": "number"},
                "deals": {"type": "array", "items": {"$ref": "#/definitions/Deal"}}
            }
        },
        "ProtectionStatus": {
            "type": "object",
            "description": "Equity protection status snapshot for one account",
            "properties": {
                "account_number": {"type": "string"},
                "protection_mode": {"type": "string", "enum": ["Equity", "Balance"]},
                "trading_blocked": {"type": "boolean"},
                "block_reason": {"type": "string", "x-nullable": True},
                "balance": {"type": "number"},
                "equity": {"type": "number"},
                "margin_level": {"type": "number"},
                "current_value": {"type": "number"},
                "daily_starting_value": {"type": "number"},
                "historical_peak": {"type": "number"},
                "peak_equity": {"type": "number"},
                "peak_balance": {"type": "number"},
                "daily_drawdown_pct": {"type": "number"},
                "total_drawdown_pct": {"type": "number"},
                "current_equity_balance_diff": {"type": "number"},
                "current_equity_balance_pct": {"type": "number"},
                "max_daily_loss_pct": {"type": "number"},
                "max_total_drawdown_pct": {"type": "number"},
                "max_daily_loss_abs": {"type": "number"},
                "max_total_drawdown_abs": {"type": "number"},
                "min_margin_level_pct": {"type": "number"},
                "action": {"type": "string", "enum": ["close_all", "close_losing", "close_losers_only", "close_profitable", "notify_only"]},
                "heartbeat_interval": {"type": "number"},
                "order_check_interval": {"type": "number"},
                "ws_update_interval": {"type": "number"},
                "auto_reset_daily": {"type": "boolean"},
                "verbose_logging": {"type": "boolean"},
                "protection_enabled": {"type": "boolean"}
            }
        },
        "AllAccountsStatus": {
            "type": "object",
            "properties": {
                "current_account": {"type": "string", "x-nullable": True, "description": "Currently active MT5 login"},
                "accounts": {
                    "type": "object",
                    "additionalProperties": {"$ref": "#/definitions/ProtectionStatus"},
                    "description": "Map of account_number → ProtectionStatus"
                }
            }
        },
        "ModifyOrderResult": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "example": "Order modified"},
                "result": {
                    "type": "object",
                    "properties": {
                        "retcode": {"type": "integer", "example": 10009},
                        "order": {"type": "integer", "description": "Order ticket"},
                        "price": {"type": "number"},
                        "comment": {"type": "string"},
                        "request_id": {"type": "integer"}
                    }
                }
            }
        }
    },
    "specs": [
        {
            "endpoint": "apispec_1",
            "route": "/apispec_1.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
    "headers": [],
}

