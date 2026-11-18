from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import logging
from flasgger import swag_from
from middleware.auth import require_api_key
from errors import MT5ConnectionError, DataError
from utils.error_handler import format_error_response, get_request_context
from swagger_specs import (
    get_all_symbols_spec, search_symbols_spec, get_symbol_info_spec,
    get_symbol_tick_spec, get_market_book_spec
)

symbol_bp = Blueprint("symbol", __name__)
logger = logging.getLogger(__name__)


@symbol_bp.route("/symbols")
@require_api_key
@swag_from(get_all_symbols_spec)
def get_all_symbols():
    try:
        symbols = mt5.symbols_get()
        if symbols is None:
            raise MT5ConnectionError("Failed to get symbols", endpoint="/symbols", request_context=get_request_context(request))
        return jsonify([s.name for s in symbols])
    except MT5ConnectionError as e:
        return format_error_response(e, 500)
    except Exception as e:
        logger.error("get_all_symbols: %s", e)
        return format_error_response(e, 500, endpoint="/symbols", request_context=get_request_context(request))


@symbol_bp.route("/symbols/search")
@require_api_key
@swag_from(search_symbols_spec)
def search_symbols():
    try:
        group = request.args.get("group", "*")
        symbols = mt5.symbols_get(group=group)
        if symbols is None:
            raise MT5ConnectionError("Failed to search symbols", endpoint="/symbols/search", request_context=get_request_context(request))
        return jsonify([s.name for s in symbols])
    except MT5ConnectionError as e:
        return format_error_response(e, 500)
    except Exception as e:
        logger.error("search_symbols: %s", e)
        return format_error_response(e, 500, endpoint="/symbols/search", request_context=get_request_context(request))


@symbol_bp.route("/symbols/quotes")
@require_api_key
def get_symbols_quotes():
    """
    One-shot snapshot of every tradable symbol with its current quote.

    Used by the symbol matcher: when vision can't read the ticker off a chart,
    the bot compares the signal's price levels against this snapshot to work
    out which instruments actually trade in that range.

    Query params:
        group  — MT5 symbols_get() filter, e.g. "*,!*Stocks*" (default "*")
        select — 1/true to pull symbols into Market Watch so unquoted ones get
                 a bid/ask (MT5 only ticks symbols that are selected)
        limit  — cap on how many symbols the select pass touches (default 500)
    """
    try:
        group = request.args.get("group", "*")
        do_select = str(request.args.get("select", "0")).lower() in ("1", "true", "yes")
        try:
            limit = int(request.args.get("limit", 500))
        except (TypeError, ValueError):
            limit = 500

        symbols = mt5.symbols_get(group=group) if group != "*" else mt5.symbols_get()
        if symbols is None:
            raise MT5ConnectionError(
                "Failed to get symbols", endpoint="/symbols/quotes",
                request_context=get_request_context(request),
            )

        result = []
        unquoted = []
        for s in symbols:
            row = {
                "name": s.name,
                "bid": s.bid,
                "ask": s.ask,
                "digits": s.digits,
                "visible": s.visible,
                "path": s.path,
                "description": s.description,
                "trade_mode": s.trade_mode,
            }
            result.append(row)
            if not s.bid and not s.ask:
                unquoted.append(row)

        # MT5 only streams prices for symbols in Market Watch — everything else
        # reads back as 0.0. Selecting them makes the quote available, so do that
        # for a bounded slice when the caller asks for it.
        if do_select and unquoted:
            for row in unquoted[:limit]:
                try:
                    if not mt5.symbol_select(row["name"], True):
                        continue
                    info = mt5.symbol_info(row["name"])
                    if info is not None:
                        row["bid"] = info.bid
                        row["ask"] = info.ask
                        row["digits"] = info.digits
                        row["visible"] = info.visible
                except Exception:  # one bad symbol must not kill the snapshot
                    continue

        return jsonify(result)
    except MT5ConnectionError as e:
        return format_error_response(e, 500)
    except Exception as e:
        logger.error("get_symbols_quotes: %s", e)
        return format_error_response(e, 500, endpoint="/symbols/quotes", request_context=get_request_context(request))


@symbol_bp.route("/symbol_info/<symbol>")
@require_api_key
@swag_from(get_symbol_info_spec)
def get_symbol_info(symbol):
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise DataError(f"Symbol not found: {symbol}", endpoint=f"/symbol_info/{symbol}", request_context=get_request_context(request))
        return jsonify(info._asdict())
    except DataError as e:
        return format_error_response(e, 404)
    except Exception as e:
        logger.error("get_symbol_info: %s", e)
        return format_error_response(e, 500, endpoint=f"/symbol_info/{symbol}", request_context=get_request_context(request))


@symbol_bp.route("/symbol_info_tick/<symbol>")
@require_api_key
@swag_from(get_symbol_tick_spec)
def get_symbol_info_tick(symbol):
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise DataError(f"No tick for symbol: {symbol}", endpoint=f"/symbol_info_tick/{symbol}", request_context=get_request_context(request))
        return jsonify(tick._asdict())
    except DataError as e:
        return format_error_response(e, 404)
    except Exception as e:
        logger.error("get_symbol_info_tick: %s", e)
        return format_error_response(e, 500, endpoint=f"/symbol_info_tick/{symbol}", request_context=get_request_context(request))


@symbol_bp.route("/market_book/<symbol>")
@require_api_key
@swag_from(get_market_book_spec)
def get_market_book(symbol):
    try:
        if not mt5.market_book_add(symbol):
            raise MT5ConnectionError(f"Cannot subscribe to book for: {symbol}", endpoint=f"/market_book/{symbol}", request_context=get_request_context(request))
        book = mt5.market_book_get(symbol)
        mt5.market_book_release(symbol)
        if book is None:
            raise DataError("Failed to get market book", endpoint=f"/market_book/{symbol}", request_context=get_request_context(request))
        return jsonify([item._asdict() for item in book])
    except (MT5ConnectionError, DataError) as e:
        return format_error_response(e, 400 if isinstance(e, MT5ConnectionError) else 404)
    except Exception as e:
        logger.error("get_market_book: %s", e)
        return format_error_response(e, 500, endpoint=f"/market_book/{symbol}", request_context=get_request_context(request))

