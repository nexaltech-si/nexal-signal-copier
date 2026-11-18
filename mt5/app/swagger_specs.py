"""
Comprehensive Swagger/OpenAPI specifications for all MT5 API endpoints.
These specs are used by Flasgger to generate interactive API documentation.
"""

# ============================================================================
# HEALTH & SYSTEM ENDPOINTS
# ============================================================================

health_check_spec = {
    "tags": ["Health"],
    "summary": "Health Check",
    "description": "Check if the server and MT5 connection are alive",
    "responses": {
        "200": {
            "description": "Server is healthy",
            "schema": {
                "$ref": "#/definitions/HealthStatus"
            }
        }
    }
}

account_info_spec = {
    "tags": ["Account"],
    "summary": "Get Account Information",
    "description": "Retrieve full MT5 account details including balance, equity, margin, leverage, etc.",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Account information retrieved successfully",
            "schema": {
                "$ref": "#/definitions/AccountInfo"
            }
        },
        "500": {
            "description": "Failed to get account info",
            "schema": {
                "$ref": "#/definitions/Error"
            }
        }
    }
}

terminal_info_spec = {
    "tags": ["Health"],
    "summary": "Get Terminal Information",
    "description": "MT5 terminal build info, paths, connection status",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Terminal information retrieved successfully",
            "schema": {"$ref": "#/definitions/TerminalInfo"}
        },
        "500": {
            "description": "Failed to get terminal info",
            "schema": {
                "$ref": "#/definitions/Error"
            }
        }
    }
}

version_spec = {
    "tags": ["Health"],
    "summary": "Get MT5 Version",
    "description": "MT5 terminal version tuple: (build, date, revision)",
    "responses": {
        "200": {
            "description": "Version information",
            "schema": {
                "type": "object",
                "properties": {
                    "build": {"type": "integer"},
                    "date": {"type": "string"},
                    "revision": {"type": "string"}
                }
            }
        }
    }
}

# ============================================================================
# SYMBOL ENDPOINTS
# ============================================================================

get_all_symbols_spec = {
    "tags": ["Symbols"],
    "summary": "Get All Symbols",
    "description": "Return all symbols available in Market Watch",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "List of symbol names",
            "schema": {
                "type": "array",
                "items": {"type": "string"},
                "example": ["EURUSD", "GBPUSD", "USDJPY"]
            }
        },
        "500": {
            "description": "Failed to get symbols",
            "schema": {
                "$ref": "#/definitions/Error"
            }
        }
    }
}

search_symbols_spec = {
    "tags": ["Symbols"],
    "summary": "Search Symbols",
    "description": "Search symbols by group pattern (e.g., *USD*, *EUR*, Forex*)",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "group",
            "in": "query",
            "type": "string",
            "default": "*",
            "description": "Symbol group pattern (wildcards supported)"
        }
    ],
    "responses": {
        "200": {
            "description": "Filtered list of symbols",
            "schema": {
                "type": "array",
                "items": {"type": "string"}
            }
        }
    }
}

get_symbol_info_spec = {
    "tags": ["Symbols"],
    "summary": "Get Symbol Information",
    "description": "Detailed symbol specification including spread, digits, contract size, etc.",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "path",
            "type": "string",
            "required": True,
            "description": "Symbol name (e.g., EURUSD)"
        }
    ],
    "responses": {
        "200": {
            "description": "Symbol information",
            "schema": {"$ref": "#/definitions/SymbolInfo"}
        },
        "404": {
            "description": "Symbol not found",
            "schema": {
                "$ref": "#/definitions/Error"
            }
        }
    }
}

get_symbol_tick_spec = {
    "tags": ["Symbols"],
    "summary": "Get Latest Tick",
    "description": "Latest bid/ask tick for a symbol",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "path",
            "type": "string",
            "required": True,
            "description": "Symbol name"
        }
    ],
    "responses": {
        "200": {
            "description": "Latest tick data",
            "schema": {"$ref": "#/definitions/Tick"}
        },
        "404": {
            "description": "No tick data available"
        }
    }
}

get_market_book_spec = {
    "tags": ["Symbols"],
    "summary": "Get Market Depth (DOM)",
    "description": "Depth-of-Market (order book) for a symbol",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "path",
            "type": "string",
            "required": True,
            "description": "Symbol name"
        }
    ],
    "responses": {
        "200": {
            "description": "Market book entries",
            "schema": {
                "type": "array",
                "items": {"$ref": "#/definitions/MarketBookEntry"}
            }
        },
        "400": {
            "description": "Cannot subscribe to book"
        }
    }
}

# ============================================================================
# MARKET DATA ENDPOINTS
# ============================================================================

fetch_data_pos_spec = {
    "tags": ["Market Data"],
    "summary": "Fetch OHLCV from Current Position",
    "description": "Get OHLCV bars starting from the current bar backwards",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "query",
            "type": "string",
            "required": True,
            "minLength": 1,
            "maxLength": 32,
            "description": "Symbol name (e.g., EURUSD)"
        },
        {
            "name": "timeframe",
            "in": "query",
            "type": "string",
            "default": "M1",
            "enum": ["M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1"],
            "description": "Timeframe"
        },
        {
            "name": "num_bars",
            "in": "query",
            "type": "integer",
            "default": 100,
            "minimum": 1,
            "maximum": 10000,
            "description": "Number of bars to fetch"
        }
    ],
    "responses": {
        "200": {
            "description": "OHLCV data",
            "schema": {
                "type": "array",
                "items": {
                    "$ref": "#/definitions/OHLCVBar"
                }
            }
        },
        "400": {
            "description": "Invalid parameters"
        }
    }
}

fetch_data_range_spec = {
    "tags": ["Market Data"],
    "summary": "Fetch OHLCV in Date Range",
    "description": "Get OHLCV bars between start and end ISO datetimes",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "query",
            "type": "string",
            "required": True,
            "minLength": 1,
            "maxLength": 32
        },
        {
            "name": "timeframe",
            "in": "query",
            "type": "string",
            "default": "M1",
            "enum": ["M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1"]
        },
        {
            "name": "from_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "Start datetime (ISO 8601 format)"
        },
        {
            "name": "to_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "End datetime (ISO 8601 format)"
        }
    ],
    "responses": {
        "200": {
            "description": "OHLCV data",
            "schema": {
                "type": "array",
                "items": {
                    "$ref": "#/definitions/OHLCVBar"
                }
            }
        }
    }
}

fetch_ticks_spec = {
    "tags": ["Market Data"],
    "summary": "Fetch Tick Data from Datetime",
    "description": "Get tick data starting from a specific datetime",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "query",
            "type": "string",
            "required": True,
            "minLength": 1,
            "maxLength": 32
        },
        {
            "name": "from_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "Start datetime (ISO 8601)"
        },
        {
            "name": "count",
            "in": "query",
            "type": "integer",
            "default": 1000,
            "minimum": 1,
            "maximum": 100000,
            "description": "Number of ticks"
        },
        {
            "name": "flags",
            "in": "query",
            "type": "integer",
            "default": 1,
            "minimum": 0,
            "maximum": 3,
            "description": "Tick flags: 0=ALL, 1=INFO, 2=TRADE"
        }
    ],
    "responses": {
        "200": {
            "description": "Tick data",
            "schema": {
                "type": "array",
                "items": {"$ref": "#/definitions/Tick"}
            }
        }
    }
}

fetch_ticks_range_spec = {
    "tags": ["Market Data"],
    "summary": "Fetch Tick Data in Range",
    "description": "Get tick data between start and end datetimes",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "query",
            "type": "string",
            "required": True,
            "minLength": 1,
            "maxLength": 32
        },
        {
            "name": "from_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "Start datetime (ISO 8601)"
        },
        {
            "name": "to_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "End datetime (ISO 8601)"
        },
        {
            "name": "flags",
            "in": "query",
            "type": "integer",
            "default": 1,
            "minimum": 0,
            "maximum": 3
        }
    ],
    "responses": {
        "200": {
            "description": "Tick data"
        }
    }
}

# ============================================================================
# ORDER ENDPOINTS
# ============================================================================

send_market_order_spec = {
    "tags": ["Orders"],
    "summary": "Send Market Order",
    "description": "Execute an immediate BUY or SELL market order",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "$ref": "#/definitions/OrderRequest"
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Order executed successfully",
            "schema": {
                "$ref": "#/definitions/TradeResult"
            }
        },
        "400": {
            "description": "Order failed",
            "schema": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "mt5_error": {"type": "string"},
                    "retcode": {"type": "integer"}
                }
            }
        }
    }
}

send_pending_order_spec = {
    "tags": ["Orders"],
    "summary": "Send Pending Order",
    "description": "Place a pending order (LIMIT, STOP, STOP_LIMIT)",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "$ref": "#/definitions/PendingOrderRequest"
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Pending order placed",
            "schema": {
                "$ref": "#/definitions/TradeResult"
            }
        },
        "400": {
            "description": "Order failed"
        }
    }
}

cancel_order_spec = {
    "tags": ["Orders"],
    "summary": "Cancel Pending Order",
    "description": "Cancel a pending order by ticket number",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["ticket"],
                "properties": {
                    "ticket": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Order ticket number"
                    }
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Order cancelled",
            "schema": {
                "$ref": "#/definitions/TradeResult"
            }
        }
    }
}

modify_order_spec = {
    "tags": ["Orders"],
    "summary": "Modify Pending Order",
    "description": "Modify price, SL, TP, or expiration of a pending order",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "$ref": "#/definitions/ModifyOrderRequest"
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Order modified",
            "schema": {"$ref": "#/definitions/ModifyOrderResult"}
        }
    }
}

close_all_orders_spec = {
    "tags": ["Orders"],
    "summary": "Close All Pending Orders",
    "description": "Cancel all pending orders with optional filtering by magic, symbol, or order type",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": False,
            "schema": {
                "type": "object",
                "properties": {
                    "magic": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 2147483647,
                        "description": "Filter by magic number"
                    },
                    "symbol": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 32,
                        "description": "Filter by symbol"
                    },
                    "order_type": {
                        "type": "string",
                        "enum": ["BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "BUY_STOP_LIMIT", "SELL_STOP_LIMIT"],
                        "description": "Filter by order type"
                    }
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Orders cancelled",
            "schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "count": {"type": "integer"},
                    "results": {
                        "type": "array",
                        "items": {"type": "object"}
                    }
                }
            }
        }
    }
}

# ============================================================================
# POSITION ENDPOINTS
# ============================================================================

positions_total_spec = {
    "tags": ["Positions"],
    "summary": "Get Total Open Positions",
    "description": "Get the count of currently open positions",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Position count",
            "schema": {
                "type": "object",
                "properties": {
                    "total": {"type": "integer"}
                }
            }
        }
    }
}

get_positions_spec = {
    "tags": ["Positions"],
    "summary": "Get All Open Positions",
    "description": "Retrieve all open positions, optionally filtered by magic number",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "magic",
            "in": "query",
            "type": "integer",
            "description": "Filter by magic number"
        }
    ],
    "responses": {
        "200": {
            "description": "List of positions",
            "schema": {
                "type": "array",
                "items": {
                    "$ref": "#/definitions/Position"
                }
            }
        }
    }
}

get_orders_spec = {
    "tags": ["Positions"],
    "summary": "Get All Pending Orders",
    "description": "Retrieve all pending orders, optionally filtered by magic number",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "magic",
            "in": "query",
            "type": "integer",
            "description": "Filter by magic number"
        }
    ],
    "responses": {
        "200": {
            "description": "List of orders",
            "schema": {
                "type": "object",
                "properties": {
                    "orders": {"type": "array"}
                }
            }
        }
    }
}

close_position_spec = {
    "tags": ["Positions"],
    "summary": "Close Position",
    "description": "Close an open position fully or partially",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["position"],
                "properties": {
                    "position": {
                        "type": "object",
                        "description": "Full position dictionary as returned by GET /positions",
                        "required": ["ticket", "type", "symbol", "volume"]
                    },
                    "volume": {
                        "type": "number",
                        "minimum": 0.01,
                        "maximum": 100,
                        "description": "Optional volume to close (partial close). If omitted, full volume is closed."
                    }
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Position closed",
            "schema": {
                "$ref": "#/definitions/TradeResult"
            }
        }
    }
}

close_partial_spec = {
    "tags": ["Positions"],
    "summary": "Partially Close Position",
    "description": "Close a portion of an open position",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["position", "volume"],
                "properties": {
                    "position": {"type": "object"},
                    "volume": {
                        "type": "number",
                        "description": "Volume to close (must be <= position volume)"
                    }
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Partial close successful"
        }
    }
}

close_all_positions_spec = {
    "tags": ["Positions"],
    "summary": "Close All Positions",
    "description": "Close all open positions or filter by type/magic",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "schema": {
                "type": "object",
                "properties": {
                    "order_type": {
                        "type": "string",
                        "enum": ["BUY", "SELL", "all"],
                        "default": "all"
                    },
                    "magic": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 2147483647
                    }
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Positions closed",
            "schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "count": {"type": "integer"},
                    "results": {"type": "array"}
                }
            }
        }
    }
}

modify_sl_tp_spec = {
    "tags": ["Positions"],
    "summary": "Modify Stop Loss / Take Profit",
    "description": "Modify SL and/or TP on an open position",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "$ref": "#/definitions/ModifySLTPRequest"
            }
        }
    ],
    "responses": {
        "200": {
            "description": "SL/TP updated"
        },
        "404": {
            "description": "Position not found"
        }
    }
}

close_profitable_spec = {
    "tags": ["Positions"],
    "summary": "Close All Profitable Positions",
    "description": "Close only positions currently in profit",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "schema": {
                "type": "object",
                "properties": {
                    "magic": {"type": "integer"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Profitable positions closed"
        }
    }
}

close_losing_spec = {
    "tags": ["Positions"],
    "summary": "Close All Losing Positions",
    "description": "Close only positions currently in a loss",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "schema": {
                "type": "object",
                "properties": {
                    "magic": {"type": "integer"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Losing positions closed"
        }
    }
}

close_symbol_spec = {
    "tags": ["Positions"],
    "summary": "Close Positions by Symbol",
    "description": "Close all positions for a specific trading pair",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["symbol"],
                "properties": {
                    "symbol": {"type": "string", "example": "XAUUSD"},
                    "magic": {"type": "integer"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Positions for symbol closed"
        }
    }
}

# ============================================================================
# HISTORY ENDPOINTS
# ============================================================================

history_deals_spec = {
    "tags": ["History"],
    "summary": "Get Historical Deals",
    "description": "Retrieve deals in a date range, optionally filtered by position ticket",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "from_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "Start date (ISO 8601)"
        },
        {
            "name": "to_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "End date (ISO 8601)"
        },
        {
            "name": "position",
            "in": "query",
            "type": "integer",
            "minimum": 1,
            "description": "Filter by position ticket"
        },
        {
            "name": "symbol",
            "in": "query",
            "type": "string",
            "minLength": 1,
            "maxLength": 32,
            "description": "Filter by symbol"
        },
        {
            "name": "magic",
            "in": "query",
            "type": "integer",
            "minimum": 0,
            "maximum": 2147483647,
            "description": "Filter by magic number"
        }
    ],
    "responses": {
        "200": {
            "description": "List of deals",
            "schema": {
                "type": "array",
                "items": {"$ref": "#/definitions/Deal"}
            }
        }
    }
}

history_orders_spec = {
    "tags": ["History"],
    "summary": "Get Historical Orders",
    "description": "Retrieve orders by ticket or date range",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "ticket",
            "in": "query",
            "type": "integer",
            "minimum": 1,
            "description": "Order ticket (alternative to date range)"
        },
        {
            "name": "from_date",
            "in": "query",
            "type": "string",
            "description": "Start date (ISO 8601)"
        },
        {
            "name": "to_date",
            "in": "query",
            "type": "string",
            "description": "End date (ISO 8601)"
        }
    ],
    "responses": {
        "200": {
            "description": "List of orders",
            "schema": {
                "type": "array",
                "items": {"$ref": "#/definitions/HistoricalOrder"}
            }
        }
    }
}

get_deal_from_ticket_spec = {
    "tags": ["History"],
    "summary": "Get Deal Summary by Ticket",
    "description": "Get summarized deal information for a position ticket",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "ticket",
            "in": "query",
            "type": "integer",
            "required": True,
            "minimum": 1
        }
    ],
    "responses": {
        "200": {
            "description": "Deal summary",
            "schema": {"$ref": "#/definitions/DealSummary"}
        },
        "404": {
            "description": "No deal found"
        }
    }
}

get_order_from_ticket_spec = {
    "tags": ["History"],
    "summary": "Get Order by Ticket",
    "description": "Get order record for a specific ticket",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "ticket",
            "in": "query",
            "type": "integer",
            "required": True
        }
    ],
    "responses": {
        "200": {
            "description": "Order record",
            "schema": {"$ref": "#/definitions/HistoricalOrder"}
        },
        "404": {
            "description": "No order found"
        }
    }
}

account_stats_spec = {
    "tags": ["History"],
    "summary": "Get Account Statistics",
    "description": "Calculate trade statistics over a date range including win rate, profit factor, etc.",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "from_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "Start date (ISO 8601)"
        },
        {
            "name": "to_date",
            "in": "query",
            "type": "string",
            "required": True,
            "description": "End date (ISO 8601)"
        }
    ],
    "responses": {
        "200": {
            "description": "Trade statistics",
            "schema": {
                "type": "object",
                "properties": {
                    "total_trades": {"type": "integer"},
                    "wins": {"type": "integer"},
                    "losses": {"type": "integer"},
                    "win_rate": {"type": "number"},
                    "total_profit": {"type": "number"},
                    "gross_profit": {"type": "number"},
                    "gross_loss": {"type": "number"},
                    "profit_factor": {"type": "number"},
                    "avg_win": {"type": "number"},
                    "avg_loss": {"type": "number"},
                    "total_commission": {"type": "number"},
                    "total_swap": {"type": "number"}
                }
            }
        }
    }
}

# ============================================================================
# TRADE LIFECYCLE ENDPOINTS
# ============================================================================

trade_lifecycle_spec = {
    "tags": ["Trade Lifecycle"],
    "summary": "Get Complete Trade Lifecycle",
    "description": "Get full trade lifecycle including order, deals, position, and history",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "ticket",
            "in": "query",
            "type": "integer",
            "required": True,
            "minimum": 1,
            "description": "Order/position ticket"
        },
        {
            "name": "days_back",
            "in": "query",
            "type": "integer",
            "default": 30,
            "minimum": 1,
            "maximum": 365,
            "description": "Days to search history"
        }
    ],
    "responses": {
        "200": {
            "description": "Complete trade lifecycle",
            "schema": {
                "$ref": "#/definitions/TradeLifecycle"
            }
        }
    }
}

trade_status_spec = {
    "tags": ["Trade Lifecycle"],
    "summary": "Quick Trade Status Check",
    "description": "Get current status of a trade (PENDING, RUNNING, CLOSED_PROFIT, etc.)",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "ticket",
            "in": "query",
            "type": "integer",
            "required": True
        }
    ],
    "responses": {
        "200": {
            "description": "Trade status",
            "schema": {
                "type": "object",
                "properties": {
                    "ticket": {"type": "integer"},
                    "status": {"type": "string"},
                    "is_open": {"type": "boolean"},
                    "current_profit": {"type": "number"},
                    "symbol": {"type": "string"},
                    "type": {"type": "string"}
                }
            }
        }
    }
}

batch_trade_status_spec = {
    "tags": ["Trade Lifecycle"],
    "summary": "Batch Trade Status Check",
    "description": "Get status for multiple tickets in one call",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["tickets"],
                "properties": {
                    "tickets": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "minItems": 1,
                        "maxItems": 100,
                        "example": [12345, 12346, 12347]
                    }
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Batch status results",
            "schema": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticket": {"type": "integer"},
                                "status": {"type": "string"},
                                "is_open": {"type": "boolean"}
                            }
                        }
                    }
                }
            }
        }
    }
}

trade_search_spec = {
    "tags": ["Trade Lifecycle"],
    "summary": "Search Trades",
    "description": "Search trades by symbol, magic number, or time range",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "query",
            "type": "string",
            "minLength": 1,
            "maxLength": 32,
            "description": "Filter by symbol"
        },
        {
            "name": "magic",
            "in": "query",
            "type": "integer",
            "minimum": 0,
            "maximum": 2147483647,
            "description": "Filter by magic number"
        },
        {
            "name": "from_date",
            "in": "query",
            "type": "string",
            "description": "Start date (ISO 8601)"
        },
        {
            "name": "to_date",
            "in": "query",
            "type": "string",
            "description": "End date (ISO 8601)"
        },
        {
            "name": "status",
            "in": "query",
            "type": "string",
            "enum": ["CLOSED_PROFIT", "CLOSED_LOSS", "CLOSED_BREAKEVEN"],
            "description": "Filter by status"
        }
    ],
    "responses": {
        "200": {
            "description": "Trade search results",
            "schema": {
                "type": "object",
                "properties": {
                    "trades": {"type": "array"},
                    "count": {"type": "integer"}
                }
            }
        }
    }
}

# ============================================================================
# SEASONAL ANALYSIS ENDPOINTS
# ============================================================================

seasonal_analysis_spec = {
    "tags": ["Seasonal"],
    "summary": "Get Seasonal Analysis",
    "description": "Compute monthly seasonal tendencies for a symbol using historical D1 data",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "symbol",
            "in": "path",
            "type": "string",
            "required": True,
            "minLength": 1,
            "maxLength": 32,
            "description": "Symbol name (e.g., EURUSD)"
        },
        {
            "name": "years",
            "in": "query",
            "type": "integer",
            "default": 20,
            "minimum": 1,
            "maximum": 30,
            "description": "Number of years of history (max 30)"
        }
    ],
    "responses": {
        "200": {
            "description": "Seasonal analysis data",
            "schema": {
                "$ref": "#/definitions/SeasonalAnalysis"
            }
        },
        "404": {
            "description": "No data available for symbol"
        }
    }
}

# ============================================================================
# PROTECTION ENDPOINTS
# ============================================================================

get_protection_config_spec = {
    "tags": ["Protection"],
    "summary": "Get Protection Configuration",
    "description": "Retrieve the current equity protection settings",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Current protection configuration"
        }
    }
}

update_protection_config_spec = {
    "tags": ["Protection"],
    "summary": "Update Protection Configuration",
    "description": "Update protection settings with hot-reload",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "properties": {
                    "max_daily_loss_pct": {"type": "number", "minimum": 0.01, "maximum": 100},
                    "max_total_drawdown_pct": {"type": "number", "minimum": 0.01, "maximum": 100},
                    "protection_mode": {"type": "string", "enum": ["equity", "balance"]},
                    "verbose_logging": {"type": "boolean"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Configuration updated"
        }
    }
}

enable_protection_spec = {
    "tags": ["Protection"],
    "summary": "Enable Protection",
    "description": "Start the equity protection monitoring service",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Protection enabled"
        }
    }
}

disable_protection_spec = {
    "tags": ["Protection"],
    "summary": "Disable Protection",
    "description": "Stop the equity protection monitoring service",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Protection disabled"
        }
    }
}

get_protection_status_spec = {
    "tags": ["Protection"],
    "summary": "Get Protection Status",
    "description": "Get detailed protection status for the current account",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Protection status information",
            "schema": {"$ref": "#/definitions/ProtectionStatus"}
        }
    }
}

get_all_accounts_status_spec = {
    "tags": ["Protection"],
    "summary": "Get All Accounts Status",
    "description": "Get protection status for all accounts with historical data",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "All accounts status",
            "schema": {"$ref": "#/definitions/AllAccountsStatus"}
        }
    }
}

reset_account_block_spec = {
    "tags": ["Protection"],
    "summary": "Reset Account Block",
    "description": "Manually unblock trading for an account",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "schema": {
                "type": "object",
                "properties": {
                    "account_number": {"type": "string", "minLength": 1, "maxLength": 32}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Block reset successful"
        }
    }
}

toggle_verbose_logging_spec = {
    "tags": ["Protection"],
    "summary": "Toggle Verbose Logging",
    "description": "Enable or disable verbose logging for protection service",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Verbose logging toggled"
        }
    }
}

manual_close_all_spec = {
    "tags": ["Protection"],
    "summary": "Manual Full Liquidation",
    "description": "Panic button: close all positions and cancel all orders",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Full liquidation triggered"
        }
    }
}

manual_close_profitable_spec = {
    "tags": ["Protection"],
    "summary": "Manual Profit Liquidation",
    "description": "Close all positions currently in profit",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Profitable positions closed"
        }
    }
}

manual_close_losing_spec = {
    "tags": ["Protection"],
    "summary": "Manual Loss Liquidation",
    "description": "Close all positions currently in loss",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Losing positions closed"
        }
    }
}

manual_close_symbol_spec = {
    "tags": ["Protection"],
    "summary": "Manual Symbol Liquidation",
    "description": "Close all positions for a specific symbol",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["symbol"],
                "properties": {
                    "symbol": {"type": "string", "example": "XAUUSD"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Symbol positions closed"
        }
    }
}

# ============================================================================
# METRICS ENDPOINTS
# ============================================================================

get_metrics_spec = {
    "tags": ["Metrics"],
    "summary": "Get API Metrics",
    "description": "Returns request counts, response times, and error rates",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "API performance metrics"
        }
    }
}

metrics_health_spec = {
    "tags": ["Metrics"],
    "summary": "Health Metrics",
    "description": "Returns system health indicators and uptime",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Health status metrics"
        }
    }
}

reset_metrics_spec = {
    "tags": ["Metrics"],
    "summary": "Reset Metrics",
    "description": "Clear all collected API performance metrics",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Metrics reset successfully"
        }
    }
}

# ============================================================================
# WEBSOCKET ENDPOINTS
# ============================================================================

websocket_status_spec = {
    "tags": ["WebSocket"],
    "summary": "WebSocket Status",
    "description": "Get current WebSocket connection and subscription counts",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "WebSocket status info"
        }
    }
}

get_all_subscriptions_spec = {
    "tags": ["WebSocket"],
    "summary": "Get All Subscriptions",
    "description": "Get detailed list of all active WebSocket subscriptions",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Subscription list"
        }
    }
}

websocket_info_spec = {
    "tags": ["WebSocket"],
    "summary": "WebSocket API Info",
    "description": "Information about available WebSocket events and usage",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "API documentation for WebSocket"
        }
    }
}

get_clients_spec = {
    "tags": ["WebSocket"],
    "summary": "Get Connected Clients",
    "description": "List all currently connected WebSocket session IDs",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Connected client list"
        }
    }
}

broadcast_tick_rest_spec = {
    "tags": ["WebSocket"],
    "summary": "Broadcast Tick (REST)",
    "description": "Manually trigger a tick broadcast (testing)",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["symbol"],
                "properties": {
                    "symbol": {"type": "string"},
                    "bid": {"type": "number"},
                    "ask": {"type": "number"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Broadcast successful"
        }
    }
}

subscribe_rest_spec = {
    "tags": ["WebSocket"],
    "summary": "Subscribe (REST Test)",
    "description": "Test endpoint for subscriptions",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "properties": {
                    "symbols": {"type": "array", "items": {"type": "string"}},
                    "positions": {"type": "boolean"},
                    "orders": {"type": "boolean"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Subscription info returned"
        }
    }
}

broadcast_position_rest_spec = {
    "tags": ["WebSocket"],
    "summary": "Broadcast Position (REST)",
    "description": "Manually trigger a position update broadcast (testing)",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["position"],
                "properties": {
                    "position": {"type": "object"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Broadcast successful"
        }
    }
}

broadcast_order_rest_spec = {
    "tags": ["WebSocket"],
    "summary": "Broadcast Order (REST)",
    "description": "Manually trigger an order update broadcast (testing)",
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["order"],
                "properties": {
                    "order": {"type": "object"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Broadcast successful"
        }
    }
}

# ============================================================================
# ERROR ENDPOINTS
# ============================================================================

last_error_spec = {
    "tags": ["Error"],
    "summary": "Get Last MT5 Error",
    "description": "Retrieve the last MT5 error code and message",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Error information",
            "schema": {
                "type": "object",
                "properties": {
                    "error_code": {"type": "integer"},
                    "error_message": {"type": "string"}
                }
            }
        }
    }
}

# ============================================================================
# MT5 SESSION (LOGIN / LOGOUT / STATUS)
# ============================================================================

mt5_login_spec = {
    "tags": ["MT5 Session"],
    "summary": "Login to MT5 Broker",
    "description": (
        "Connect the running MT5 terminal to a specific broker server and account. "
        "Credentials are kept in memory only (and persisted to disk only if "
        "MT5_PERSIST_LOGIN=1). On success, the equity-protection heartbeat will "
        "reuse these credentials to auto-reconnect after any disconnect."
    ),
    "security": [{"ApiKeyAuth": []}],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": True,
            "schema": {
                "type": "object",
                "required": ["login", "password", "server"],
                "properties": {
                    "login":    {"type": "integer", "example": 12345678,
                                 "description": "Broker account number"},
                    "password": {"type": "string", "format": "password",
                                 "description": "Trading or investor password"},
                    "server":   {"type": "string", "example": "ICMarketsSC-Demo",
                                 "description": "Exact broker server name (case-sensitive)"},
                    "path":     {"type": "string",
                                 "description": "Optional absolute path to terminal64.exe"},
                    "timeout":  {"type": "integer", "default": 60000,
                                 "description": "Initialize timeout in milliseconds"}
                }
            }
        }
    ],
    "responses": {
        "200": {
            "description": "Login successful",
            "schema": {
                "type": "object",
                "properties": {
                    "ok":      {"type": "boolean", "example": True},
                    "login":   {"type": "integer"},
                    "server":  {"type": "string"},
                    "account": {"$ref": "#/definitions/AccountInfo"}
                }
            }
        },
        "401": {
            "description": "Invalid credentials or server unreachable",
            "schema": {
                "type": "object",
                "properties": {
                    "ok":    {"type": "boolean", "example": False},
                    "error": {"type": "string", "example": "(-6) Authorization failed"}
                }
            }
        },
        "400": {"description": "Invalid request body", "schema": {"$ref": "#/definitions/Error"}}
    }
}

mt5_logout_spec = {
    "tags": ["MT5 Session"],
    "summary": "Logout from MT5",
    "description": "Disconnect from the broker and forget stored credentials.",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Logged out",
            "schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean", "example": True}}
            }
        }
    }
}

mt5_login_status_spec = {
    "tags": ["MT5 Session"],
    "summary": "Get MT5 Session Status",
    "description": "Show whether a session is active, the broker server, login id, and current account info.",
    "security": [{"ApiKeyAuth": []}],
    "responses": {
        "200": {
            "description": "Session status",
            "schema": {
                "type": "object",
                "properties": {
                    "logged_in": {"type": "boolean"},
                    "login":     {"type": "integer", "x-nullable": True},
                    "server":    {"type": "string", "x-nullable": True},
                    "path":      {"type": "string", "x-nullable": True},
                    "connected": {"type": "boolean", "description": "Terminal currently connected to broker"},
                    "account":   {"$ref": "#/definitions/AccountInfo"},
                    "last_error": {"type": "string", "x-nullable": True}
                }
            }
        }
    }
}
