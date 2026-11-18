"""
Input validation schemas using marshmallow.
"""
from marshmallow import Schema, fields, validates, validates_schema, validate, ValidationError as MarshmallowError
from errors import ValidationError


class MT5LoginSchema(Schema):
    """Schema for MT5 login (broker account credentials)."""
    login = fields.Int(required=True, validate=validate.Range(min=1, max=2**63 - 1))
    password = fields.Str(required=True, validate=validate.Length(min=1, max=128))
    server = fields.Str(required=True, validate=validate.Length(min=1, max=128))
    path = fields.Str(allow_none=True, validate=validate.Length(max=512),
                      metadata={"description": "Optional absolute path to terminal64.exe"})
    timeout = fields.Int(load_default=60000, validate=validate.Range(min=1000, max=300000),
                         metadata={"description": "Initialize timeout in milliseconds"})


class MarketOrderSchema(Schema):
    """Schema for market order requests."""
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=32))
    volume = fields.Float(required=True, validate=validate.Range(min=0.01, max=100))
    type = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "0", "1"]))
    sl = fields.Float(allow_none=True, validate=validate.Range(min=0))
    tp = fields.Float(allow_none=True, validate=validate.Range(min=0))
    deviation = fields.Int(load_default=20, validate=validate.Range(min=0, max=1000))
    magic = fields.Int(load_default=0, validate=validate.Range(min=0, max=2147483647))
    comment = fields.Str(load_default="", validate=validate.Length(max=128))
    type_filling = fields.Str(allow_none=True, validate=validate.OneOf([
        "ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"
    ]))


class PendingOrderSchema(Schema):
    """Schema for pending order requests."""
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=32))
    volume = fields.Float(required=True, validate=validate.Range(min=0.01, max=100))
    type = fields.Str(required=True, validate=validate.OneOf([
        "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP",
        "BUY_STOP_LIMIT", "SELL_STOP_LIMIT"
    ]))
    price = fields.Float(required=True, validate=validate.Range(min=0))
    stoplimit_price = fields.Float(allow_none=True, validate=validate.Range(min=0))
    sl = fields.Float(allow_none=True, validate=validate.Range(min=0))
    tp = fields.Float(allow_none=True, validate=validate.Range(min=0))
    deviation = fields.Int(load_default=20, validate=validate.Range(min=0, max=1000))
    magic = fields.Int(load_default=0, validate=validate.Range(min=0, max=2147483647))
    comment = fields.Str(load_default="", validate=validate.Length(max=128))
    expiration = fields.DateTime(allow_none=True, format="iso")
    type_filling = fields.Str(allow_none=True, validate=validate.OneOf([
        "ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"
    ]))

    @validates_schema
    def validate_stoplimit_price(self, data, **kwargs):
        """Validate stoplimit_price is provided for STOP_LIMIT orders."""
        if data.get("type") in ["BUY_STOP_LIMIT", "SELL_STOP_LIMIT"] and data.get("stoplimit_price") is None:
            raise MarshmallowError("stoplimit_price is required for STOP_LIMIT orders")


class CancelOrderSchema(Schema):
    """Schema for cancel order requests."""
    ticket = fields.Int(required=True, validate=validate.Range(min=1))


class ModifyOrderSchema(Schema):
    """Schema for modify order requests."""
    ticket = fields.Int(required=True, validate=validate.Range(min=1))
    price = fields.Float(allow_none=True, validate=validate.Range(min=0))
    sl = fields.Float(allow_none=True, validate=validate.Range(min=0))
    tp = fields.Float(allow_none=True, validate=validate.Range(min=0))
    stoplimit_price = fields.Float(allow_none=True, validate=validate.Range(min=0))
    expiration = fields.DateTime(allow_none=True, format="iso")


class CloseAllOrdersSchema(Schema):
    """Schema for close all orders requests."""
    magic = fields.Int(allow_none=True, validate=validate.Range(min=0, max=2147483647))
    symbol = fields.Str(allow_none=True, validate=validate.Length(min=1, max=32))
    order_type = fields.Str(allow_none=True, validate=validate.OneOf([
        "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP",
        "BUY_STOP_LIMIT", "SELL_STOP_LIMIT"
    ]))


class ClosePositionSchema(Schema):
    """Schema for close position requests."""
    position = fields.Dict(required=True)
    volume = fields.Float(allow_none=True, validate=validate.Range(min=0.01, max=100))


class ModifySLTPSchema(Schema):
    """Schema for modify SL/TP requests."""
    position = fields.Int(required=True, validate=validate.Range(min=1))
    sl = fields.Float(allow_none=True, validate=validate.Range(min=0))
    tp = fields.Float(allow_none=True, validate=validate.Range(min=0))


class CloseAllPositionsSchema(Schema):
    """Schema for close all positions requests."""
    order_type = fields.Str(allow_none=True, validate=validate.OneOf(["BUY", "SELL", "all"]))
    magic = fields.Int(allow_none=True, validate=validate.Range(min=0, max=2147483647))


class FetchDataPosSchema(Schema):
    """Schema for fetch data from position requests."""
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=32))
    timeframe = fields.Str(load_default="M1", validate=validate.OneOf([
        "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
        "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1"
    ]))
    num_bars = fields.Int(load_default=100, validate=validate.Range(min=1, max=10000))


class FetchDataRangeSchema(Schema):
    """Schema for fetch data in range requests."""
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=32))
    timeframe = fields.Str(load_default="M1", validate=validate.OneOf([
        "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
        "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1"
    ]))
    from_date = fields.Str(required=True)
    to_date = fields.Str(required=True)


class FetchTicksSchema(Schema):
    """Schema for fetch ticks requests."""
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=32))
    from_date = fields.Str(required=True, data_key="from")
    count = fields.Int(load_default=1000, validate=validate.Range(min=1, max=100000))
    flags = fields.Int(load_default=1, validate=validate.Range(min=0, max=3))


class FetchTicksRangeSchema(Schema):
    """Schema for fetch ticks in range requests."""
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=32))
    from_date = fields.Str(required=True)
    to_date = fields.Str(required=True)
    flags = fields.Int(load_default=1, validate=validate.Range(min=0, max=3))


class HistoryDealsGetSchema(Schema):
    """Schema for history deals requests."""
    from_date = fields.Str(required=True)
    to_date = fields.Str(required=True)
    position = fields.Int(allow_none=True, validate=validate.Range(min=1))
    symbol = fields.Str(allow_none=True, validate=validate.Length(min=1, max=32))
    magic = fields.Int(allow_none=True, validate=validate.Range(min=0, max=2147483647))


class HistoryOrdersGetSchema(Schema):
    """Schema for history orders requests."""
    ticket = fields.Int(allow_none=True, validate=validate.Range(min=1))
    from_date = fields.Str(allow_none=True)
    to_date = fields.Str(allow_none=True)


class DealFromTicketSchema(Schema):
    """Schema for get deal from ticket requests."""
    ticket = fields.Int(required=True, validate=validate.Range(min=1))


class OrderFromTicketSchema(Schema):
    """Schema for get order from ticket requests."""
    ticket = fields.Int(required=True, validate=validate.Range(min=1))


class AccountStatsSchema(Schema):
    """Schema for account stats requests."""
    from_date = fields.Str(required=True)
    to_date = fields.Str(required=True)


class TradeLifecycleSchema(Schema):
    """Schema for trade lifecycle requests."""
    ticket = fields.Int(required=True, validate=validate.Range(min=1))
    days_back = fields.Int(load_default=30, validate=validate.Range(min=1, max=365))


class TradeStatusSchema(Schema):
    """Schema for trade status requests."""
    ticket = fields.Int(required=True, validate=validate.Range(min=1))


class TradeBatchStatusSchema(Schema):
    """Schema for batch trade status requests."""
    tickets = fields.List(fields.Int(validate=validate.Range(min=1)), required=True, validate=validate.Length(min=1, max=100))


class TradeSearchSchema(Schema):
    """Schema for trade search requests."""
    symbol = fields.Str(allow_none=True, validate=validate.Length(min=1, max=32))
    magic = fields.Int(allow_none=True, validate=validate.Range(min=0, max=2147483647))
    status = fields.Str(allow_none=True, validate=validate.OneOf([
        "CLOSED_PROFIT", "CLOSED_LOSS", "CLOSED_BREAKEVEN"
    ]))
    from_date = fields.Str(allow_none=True)
    to_date = fields.Str(allow_none=True)


class SeasonalSchema(Schema):
    """Schema for seasonal analysis requests."""
    years = fields.Int(load_default=20, validate=validate.Range(min=1, max=30))


class ProtectionConfigSchema(Schema):
    """Schema for protection configuration updates."""
    max_daily_loss_pct = fields.Float(allow_none=True, validate=validate.Range(min=0.01, max=100))
    max_total_drawdown_pct = fields.Float(allow_none=True, validate=validate.Range(min=0.01, max=100))
    protection_mode = fields.Str(allow_none=True, validate=validate.OneOf(["equity", "balance"]))
    verbose_logging = fields.Bool(allow_none=True)


class ResetBlockSchema(Schema):
    """Schema for resetting account block."""
    account_number = fields.Str(allow_none=True, validate=validate.Length(min=1, max=32))


def validate_request(schema: Schema, data: dict, endpoint: str = None):
    """
    Validate request data against a schema.

    Args:
        schema: Marshmallow schema to validate against
        data: Request data to validate
        endpoint: Endpoint name for error context

    Returns:
        Validated data

    Raises:
        ValidationError: If validation fails
    """
    try:
        return schema.load(data)
    except MarshmallowError as e:
        raise ValidationError(
            message="Validation failed",
            field=str(e.messages) if hasattr(e, 'messages') else str(e),
            endpoint=endpoint
        )
