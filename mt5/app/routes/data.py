from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import pandas as pd
import pytz
import logging
from datetime import datetime
from flasgger import swag_from
from middleware.auth import require_api_key
from errors import DataError, ValidationError
from utils.error_handler import format_error_response, get_request_context
from utils.validation_schemas import validate_request, FetchDataPosSchema, FetchDataRangeSchema, FetchTicksSchema, FetchTicksRangeSchema
from lib import get_timeframe, ensure_symbol_selected, parse_iso_datetime
from swagger_specs import (
    fetch_data_pos_spec, fetch_data_range_spec,
    fetch_ticks_spec, fetch_ticks_range_spec
)

data_bp = Blueprint("data", __name__)
logger = logging.getLogger(__name__)
UTC = pytz.utc




@data_bp.route("/fetch_data_pos")
@require_api_key
@swag_from(fetch_data_pos_spec)
def fetch_data_pos():
    try:
        data = {
            "symbol": request.args.get("symbol"),
            "timeframe": request.args.get("timeframe", "M1"),
            "num_bars": int(request.args.get("num_bars", 100))
        }
        validated = validate_request(FetchDataPosSchema(), data, endpoint="/fetch_data_pos")
        
        # Ensure symbol is selected in Market Watch before fetching data
        if not ensure_symbol_selected(validated["symbol"]):
            raise DataError(f"Symbol {validated['symbol']} is not available or cannot be selected in MT5 terminal",
                           endpoint="/fetch_data_pos", request_context=get_request_context(request))
        
        tf    = get_timeframe(validated["timeframe"])
        rates = mt5.copy_rates_from_pos(validated["symbol"], tf, 0, validated["num_bars"])
        if rates is None:
            ec, es = mt5.last_error()
            logger.error("Failed to fetch data for %s (timeframe=%s, num_bars=%s): MT5 error code=%s, error=%s",
                         validated["symbol"], validated["timeframe"], validated["num_bars"], ec, es)
            raise DataError(f"No data returned for {validated['symbol']}. MT5 error: {es} (code: {ec})",
                           endpoint="/fetch_data_pos", request_context=get_request_context(request))
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return jsonify(df.to_dict(orient="records"))
    except (ValidationError, DataError, ValueError) as e:
        return format_error_response(e, 400 if isinstance(e, (ValidationError, ValueError)) else 500)
    except Exception as e:
        logger.error("fetch_data_pos error: %s", e)
        return format_error_response(e, 500, endpoint="/fetch_data_pos", request_context=get_request_context(request))


@data_bp.route("/fetch_data_range")
@require_api_key
@swag_from(fetch_data_range_spec)
def fetch_data_range():
    try:
        data = {
            "symbol": request.args.get("symbol"),
            "timeframe": request.args.get("timeframe", "M1"),
            "from_date": request.args.get("from_date"),
            "to_date": request.args.get("to_date")
        }
        validated = validate_request(FetchDataRangeSchema(), data, endpoint="/fetch_data_range")
        
        # Ensure symbol is selected in Market Watch before fetching data
        if not ensure_symbol_selected(validated["symbol"]):
            raise DataError(f"Symbol {validated['symbol']} is not available or cannot be selected in MT5 terminal",
                           endpoint="/fetch_data_range", request_context=get_request_context(request))
        
        tf    = get_timeframe(validated["timeframe"])
        rates = mt5.copy_rates_range(validated["symbol"], tf, parse_iso_datetime(validated["from_date"]), parse_iso_datetime(validated["to_date"]))
        if rates is None:
            ec, es = mt5.last_error()
            logger.error("Failed to fetch data range for %s (timeframe=%s, from=%s, to=%s): MT5 error code=%s, error=%s",
                         validated["symbol"], validated["timeframe"], validated["from_date"], validated["to_date"], ec, es)
            raise DataError(f"No data returned for {validated['symbol']}. MT5 error: {es} (code: {ec})",
                           endpoint="/fetch_data_range", request_context=get_request_context(request))
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return jsonify(df.to_dict(orient="records"))
    except (ValidationError, DataError, ValueError) as e:
        return format_error_response(e, 400 if isinstance(e, (ValidationError, ValueError)) else 500)
    except Exception as e:
        logger.error("fetch_data_range error: %s", e)
        return format_error_response(e, 500, endpoint="/fetch_data_range", request_context=get_request_context(request))


@data_bp.route("/fetch_ticks")
@require_api_key
@swag_from(fetch_ticks_spec)
def fetch_ticks():
    try:
        data = {
            "symbol": request.args.get("symbol"),
            "from_date": request.args.get("from_date"),
            "count": int(request.args.get("count", 1000)),
            "flags": int(request.args.get("flags", mt5.COPY_TICKS_ALL))
        }
        validated = validate_request(FetchTicksSchema(), data, endpoint="/fetch_ticks")
        
        # Ensure symbol is selected in Market Watch before fetching data
        if not ensure_symbol_selected(validated["symbol"]):
            raise DataError(f"Symbol {validated['symbol']} is not available or cannot be selected in MT5 terminal",
                           endpoint="/fetch_ticks", request_context=get_request_context(request))
        
        ticks = mt5.copy_ticks_from(validated["symbol"], parse_iso_datetime(validated["from_date"]), validated["count"], validated["flags"])
        if ticks is None:
            ec, es = mt5.last_error()
            logger.error("Failed to fetch ticks for %s (from=%s, count=%s, flags=%s): MT5 error code=%s, error=%s",
                         validated["symbol"], validated["from_date"], validated["count"], validated["flags"], ec, es)
            raise DataError(f"No tick data returned for {validated['symbol']}. MT5 error: {es} (code: {ec})",
                           endpoint="/fetch_ticks", request_context=get_request_context(request))
        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return jsonify(df.to_dict(orient="records"))
    except (ValidationError, DataError, ValueError) as e:
        return format_error_response(e, 400 if isinstance(e, (ValidationError, ValueError)) else 500)
    except Exception as e:
        logger.error("fetch_ticks error: %s", e)
        return format_error_response(e, 500, endpoint="/fetch_ticks", request_context=get_request_context(request))


@data_bp.route("/fetch_ticks_range")
@require_api_key
@swag_from(fetch_ticks_range_spec)
def fetch_ticks_range():
    try:
        data = {
            "symbol": request.args.get("symbol"),
            "from_date": request.args.get("from_date"),
            "to_date": request.args.get("to_date"),
            "flags": int(request.args.get("flags", mt5.COPY_TICKS_ALL))
        }
        validated = validate_request(FetchTicksRangeSchema(), data, endpoint="/fetch_ticks_range")
        
        # Ensure symbol is selected in Market Watch before fetching data
        if not ensure_symbol_selected(validated["symbol"]):
            raise DataError(f"Symbol {validated['symbol']} is not available or cannot be selected in MT5 terminal",
                           endpoint="/fetch_ticks_range", request_context=get_request_context(request))
        
        ticks = mt5.copy_ticks_range(validated["symbol"], parse_iso_datetime(validated["from_date"]), parse_iso_datetime(validated["to_date"]), validated["flags"])
        if ticks is None:
            ec, es = mt5.last_error()
            logger.error("Failed to fetch ticks range for %s (from=%s, to=%s, flags=%s): MT5 error code=%s, error=%s",
                         validated["symbol"], validated["from_date"], validated["to_date"], validated["flags"], ec, es)
            raise DataError(f"No tick data returned for {validated['symbol']}. MT5 error: {es} (code: {ec})",
                           endpoint="/fetch_ticks_range", request_context=get_request_context(request))
        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return jsonify(df.to_dict(orient="records"))
    except (ValidationError, DataError, ValueError) as e:
        return format_error_response(e, 400 if isinstance(e, (ValidationError, ValueError)) else 500)
    except Exception as e:
        logger.error("fetch_ticks_range error: %s", e)
        return format_error_response(e, 500, endpoint="/fetch_ticks_range", request_context=get_request_context(request))

