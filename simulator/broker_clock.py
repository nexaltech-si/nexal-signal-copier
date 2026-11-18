"""
The broker's clock, measured — so price bars land on the real time of day.

MT5 stamps bars and ticks in broker SERVER time (often UTC+2 in winter, UTC+3 in
summer), while Telegram messages carry real UTC. A replay that mixes the two
puts every fill and every TP / SL hit hours away from the message that caused
it.

Same approach as the forex-analytics-platform (utils/timezone_utils.py
`get_broker_offset_hours`, lib/broker-time.ts): the offset is measured from the
broker's own tick clock instead of assumed, corrected once where the bars enter
the system, and everything downstream works in true UTC.

  1. tick clock    server time of the newest tick minus real UTC, rounded to the
                   nearest half hour; rejected when the tick is stale (weekend,
                   halted symbol) and the difference is no plausible offset
  2. newest bar    the same reading from the newest M1 bar, when the market is open
  3. configured    BROKER_TIMEZONE_OFFSET, the value the MT5 bridge itself uses
  4. none          treated as UTC and reported as not verified

History: a broker on the New-York-close convention (server = New York + 7 h)
changes its offset with US daylight saving, so a bar from before the last
change carries the offset of ITS date, not today's. `offset_at` handles that.
"""
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    _NEW_YORK = ZoneInfo("America/New_York")
except Exception:                                    # no tz database on this machine
    _NEW_YORK = None


CLOCK_SYMBOLS = tuple(x.strip() for x in os.environ.get(
    "BROKER_CLOCK_SYMBOLS", "BTCUSD,ETHUSD,EURUSD,XAUUSD").split(",") if x.strip())


def offset_from_tick(tick_time: Optional[float], now_ts: Optional[float] = None) -> Optional[float]:
    """Offset in hours from a tick's server-clock timestamp, or None when it is not a plausible offset."""
    if not tick_time:
        return None
    delta_hours = (float(tick_time) - (now_ts if now_ts is not None else time.time())) / 3600.0
    if not -13.0 <= delta_hours <= 15.0:
        return None
    offset = round(delta_hours * 2.0) / 2.0
    # a stale tick (market closed) also gives a "valid" number — only a reading that
    # sits on a half-hour mark, within a few minutes, is the clock and not the gap
    return offset if abs(delta_hours - offset) <= 0.1 else None


def offset_from_newest_bar(newest_bar: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    """Offset in hours from the newest M1 bar's label, when that bar is current."""
    if newest_bar is None:
        return None
    now = now or datetime.now(timezone.utc)
    label = newest_bar if newest_bar.tzinfo else newest_bar.replace(tzinfo=timezone.utc)
    gap_hours = (label - now).total_seconds() / 3600.0
    offset = round(gap_hours * 2.0) / 2.0
    return offset if abs(gap_hours - offset) <= 0.25 and abs(offset) <= 14 else None


def _new_york_offset(when: datetime) -> Optional[float]:
    if _NEW_YORK is None:
        return None
    return when.astimezone(_NEW_YORK).utcoffset().total_seconds() / 3600.0


def follows_new_york_close(offset_now: float, now: Optional[datetime] = None) -> bool:
    """Is this the usual server = New York + 7 h clock (UTC+2 winter / UTC+3 summer)?"""
    ny = _new_york_offset(now or datetime.now(timezone.utc))
    return ny is not None and abs(offset_now - (ny + 7.0)) < 0.01


def offset_at(when: datetime, offset_now: float, now: Optional[datetime] = None) -> float:
    """The broker's offset on the date of `when` (a real-UTC or close-to-UTC instant)."""
    now = now or datetime.now(timezone.utc)
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    if follows_new_york_close(offset_now, now):
        ny = _new_york_offset(when)
        if ny is not None:
            return ny + 7.0
    return offset_now


def label_to_utc(label: datetime, offset_now: float, now: Optional[datetime] = None) -> datetime:
    """A broker-stamped bar label as the real UTC instant it stands for."""
    label = label if label.tzinfo else label.replace(tzinfo=timezone.utc)
    if not offset_now:
        return label
    # the offset of the bar's own date; the label is at most a few hours from UTC,
    # so asking for the offset "at the label" picks the right side of a DST change
    # except within those few hours of the change itself (a Sunday, market closed)
    return label - timedelta(hours=offset_at(label - timedelta(hours=offset_now), offset_now, now))


async def measure(provider, symbol: str, newest_bar: Optional[datetime] = None) -> Tuple[float, str]:
    """(offset in hours, how it was found) for the broker behind `provider`."""
    raw_get = getattr(provider, "_get", None)                # MT5 REST bridge: raw tick with the server clock
    if raw_get is None:
        return 0.0, "this provider reports bar times in UTC"
    # A stale tick reads low, never high: the freshest tick of a few instruments —
    # crypto trades through the weekend — is the best reading of the server clock.
    newest_tick = None
    for name in dict.fromkeys([symbol, *CLOCK_SYMBOLS]):
        try:
            resolved = await provider.resolve_symbol(name)
            tick = await raw_get(f"/symbol_info_tick/{resolved}")
            stamp = float((tick or {}).get("time") or 0)
            if stamp and (newest_tick is None or stamp > newest_tick):
                newest_tick = stamp
        except Exception:
            continue
    offset = offset_from_tick(newest_tick)
    if offset is not None:
        return offset, "measured from the broker's tick clock"
    offset = offset_from_newest_bar(newest_bar)
    if offset is not None:
        return offset, "measured from the newest price bar"
    configured = os.environ.get("BROKER_TIMEZONE_OFFSET", "").strip()
    if configured:
        try:
            return float(configured), "from BROKER_TIMEZONE_OFFSET (market closed — could not be measured)"
        except ValueError:
            pass
    return 0.0, "NOT VERIFIED — market closed and no BROKER_TIMEZONE_OFFSET set; bar times taken as UTC"
