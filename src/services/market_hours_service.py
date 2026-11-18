"""
Market Hours Service
Checks whether the market for a given symbol is currently open.
Forex / metals: closed Friday 22:00 UTC → Sunday 22:00 UTC.
"""
from datetime import datetime, timezone


class MarketHoursService:
    # Symbols that follow standard forex hours (closed Fri 22:00 → Sun 22:00 UTC)
    FOREX_SYMBOLS = {"XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
                     "AUDUSD", "NZDUSD", "USDCAD", "EURGBP", "EURJPY", "GBPJPY"}

    def is_market_open(self, symbol: str = "") -> bool:  # noqa: ARG002
        """Return True if the market for this symbol is currently open."""
        now = datetime.now(timezone.utc)
        return self._is_forex_open(now)

    def _is_forex_open(self, now: datetime) -> bool:
        weekday = now.weekday()  # 0=Mon … 6=Sun
        hour = now.hour

        if weekday == 5:                        # All of Saturday
            return False
        if weekday == 6 and hour < 22:          # Sunday before 22:00 UTC
            return False
        if weekday == 4 and hour >= 22:         # Friday from 22:00 UTC onward
            return False
        return True

    def price_already_past_zone(
        self,
        current_price: float,
        order_type: str,
        entry_min: float,
        entry_max: float,
    ) -> bool:
        """
        Return True when price has already moved through the entry zone before
        the plan was registered, making it pointless to watch.

        For BUY plans the zone sits below current price and we wait for a
        pullback — so the zone is only stale if price is already BELOW the min.
        For SELL plans the zone sits above current price.
        """
        if order_type.upper() == "BUY":
            return current_price < entry_min
        return current_price > entry_max


market_hours_service = MarketHoursService()
