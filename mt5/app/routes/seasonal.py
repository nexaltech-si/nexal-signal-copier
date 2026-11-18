from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import pandas as pd
import logging
from flasgger import swag_from
from lib import get_timeframe, ensure_symbol_selected
from middleware.auth import require_api_key
from errors import ValidationError, DataError
from utils.error_handler import format_error_response, get_request_context
from utils.validation_schemas import validate_request, SeasonalSchema
from swagger_specs import seasonal_analysis_spec

seasonal_bp = Blueprint("seasonal", __name__)
logger = logging.getLogger(__name__)

_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@seasonal_bp.route("/seasonal/<symbol>")
@require_api_key
@swag_from(seasonal_analysis_spec)
def get_seasonal(symbol: str):
    try:
        data = {"years": request.args.get("years", 20)}
        validated = validate_request(SeasonalSchema(), data, endpoint=f"/seasonal/{symbol}")
        years = validated["years"]

        num_bars = years * 365 + 60  # extra buffer for weekends/holidays

        # Ensure symbol is selected in Market Watch before fetching data
        if not ensure_symbol_selected(symbol):
            logger.warning("seasonal: symbol %s not available in MT5 terminal", symbol)
            raise DataError(f"Symbol {symbol} is not available or cannot be selected in MT5 terminal", endpoint=f"/seasonal/{symbol}", request_context=get_request_context(request))

        tf = get_timeframe("D1")
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, num_bars)

        if rates is None or len(rates) == 0:
            err = mt5.last_error()
            logger.warning("seasonal: no D1 data for %s — mt5 error: %s", symbol, err)
            raise DataError(f"No D1 data for symbol {symbol}", endpoint=f"/seasonal/{symbol}", request_context=get_request_context(request))

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        df = df[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["close"])
        df = df.sort_index()

        # Resample to monthly: use first daily open and last daily close of each month
        monthly_open  = df["open"].resample("MS").first()
        monthly_close = df["close"].resample("MS").last()
        monthly = pd.DataFrame({"open_price": monthly_open, "close_price": monthly_close})

        # Drop incomplete months at the boundary: the in-progress current month and a first month that
        # starts mid-month would skew both the up-probability and the average of that calendar month.
        monthly = monthly.dropna()
        now_month = pd.Timestamp.now(tz="UTC").normalize().replace(day=1)
        monthly = monthly[monthly.index < now_month]
        first_bar = df.index[0]
        if len(monthly) and first_bar.day > 7 and monthly.index[0] == first_bar.normalize().replace(day=1):
            monthly = monthly.iloc[1:]

        monthly["return_pct"] = (
            (monthly["close_price"] - monthly["open_price"]) / monthly["open_price"] * 100
        )
        monthly["year"] = monthly.index.year
        monthly["month"] = monthly.index.month

        years_set = sorted(monthly["year"].unique().tolist())

        # Per-year monthly returns
        returns_by_year: dict = {}
        for yr in years_set:
            row: dict = {}
            for m_idx, m_label in enumerate(_MONTH_LABELS, start=1):
                mask = (monthly["year"] == yr) & (monthly["month"] == m_idx)
                subset = monthly[mask]
                row[m_label] = round(float(subset["return_pct"].iloc[0]), 2) if not subset.empty else None
            returns_by_year[str(yr)] = row

        # Aggregate statistics per calendar month
        probability: dict = {}
        avg_return: dict = {}
        for m_idx, m_label in enumerate(_MONTH_LABELS, start=1):
            month_data = monthly[monthly["month"] == m_idx]["return_pct"].dropna()
            if month_data.empty:
                probability[m_label] = 0.0
                avg_return[m_label] = 0.0
            else:
                probability[m_label] = round(float((month_data > 0).sum() / len(month_data) * 100), 1)
                avg_return[m_label] = round(float(month_data.mean()), 2)

        return jsonify({
            "pair":        symbol,
            "years":       years_set,
            "months":      _MONTH_LABELS,
            "probability": probability,
            "avg_return":  avg_return,
            "returns":     returns_by_year,
            "bars_fetched": len(df),
        })

    except (ValidationError, DataError, ValueError) as e:
        return format_error_response(e, 400 if isinstance(e, (ValidationError, ValueError)) else 500)
    except Exception as e:
        logger.error("seasonal %s: %s", symbol, e, exc_info=True)
        return format_error_response(e, 500, endpoint=f"/seasonal/{symbol}", request_context=get_request_context(request))

