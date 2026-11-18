"""Wording of the news alerts the bot posts to Telegram.

Kept apart from the news service so the text can be tested on its own. The
alert is short and casual: a loud headline, the event with flag and time, one
line on what it is, the numbers, and what is likely to move. The closing line
varies between events but is chosen from the event itself, so the same event
always reads the same.
"""
import hashlib
from typing import Dict, List, Optional

CURRENCY_NAMES = {
    'USD': 'dollar', 'EUR': 'euro', 'GBP': 'pound', 'JPY': 'yen',
    'CHF': 'franc', 'CAD': 'loonie', 'AUD': 'aussie',
    'NZD': 'kiwi', 'CNY': 'yuan',
}
REGION_NAMES = {
    'USD': 'US', 'EUR': 'EU', 'GBP': 'UK', 'JPY': 'JP', 'CHF': 'CH',
    'CAD': 'CA', 'AUD': 'AU', 'NZD': 'NZ', 'CNY': 'CN',
}
FLAGS = {
    'USD': '🇺🇸', 'EUR': '🇪🇺', 'GBP': '🇬🇧', 'JPY': '🇯🇵', 'CHF': '🇨🇭',
    'CAD': '🇨🇦', 'AUD': '🇦🇺', 'NZD': '🇳🇿', 'CNY': '🇨🇳', 'ALL': '🌍',
}
# Short names people actually say, for the headline.
NICKNAMES = [
    (('non-farm', 'nonfarm'), 'NFP'), (('core cpi',), 'CORE CPI'), (('cpi',), 'CPI'),
    (('core pce',), 'CORE PCE'), (('ppi',), 'PPI'), (('gdp',), 'GDP'),
    (('fomc statement', 'federal funds rate'), 'FOMC'), (('fomc',), 'FOMC'),
    (('unemployment claims', 'jobless claims'), 'JOBLESS CLAIMS'),
    (('retail sales',), 'RETAIL SALES'), (('ism', 'pmi'), 'PMI'), (('adp',), 'ADP'),
    (('rate',), 'RATE DECISION'),
]

# What an event is, in one plain sentence. First keyword found in the title wins,
# so the more specific keys come first.
EXPLAINERS = [
    (('non-farm', 'nonfarm', 'nfp'), "the monthly jobs report. biggest mover of the month, no cap"),
    (('adp',), "private jobs count, basically the NFP trailer"),
    (('unemployment claims', 'jobless claims'), "weekly count of people filing for benefits"),
    (('unemployment rate',), "how many people are out of work"),
    (('average hourly earnings', 'earnings index'), "wage growth. feeds straight into inflation fears"),
    (('core cpi', 'cpi', 'consumer price'), "THE inflation number. central banks live by it"),
    (('core pce', 'pce'), "the Fed's favourite inflation gauge"),
    (('ppi', 'producer price'), "factory-gate prices, an early inflation hint"),
    (('fomc statement', 'federal funds rate', 'rate decision', 'official bank rate', 'cash rate',
      'main refinancing rate', 'policy rate', 'overnight rate', 'interest rate'),
     "rate decision. the number is usually priced in, the wording is what hits"),
    (('fomc meeting minutes', 'minutes'), "notes from the last rate meeting. traders hunt for hints"),
    (('press conference',), "live presser. one sentence can flip the chart"),
    (('speaks', 'testifies', 'speech'), "central bank talk. unscripted, so surprises happen"),
    (('gdp',), "the big-picture score for the economy"),
    (('retail sales',), "how hard consumers are spending"),
    (('ism', 'pmi'), "business survey. above 50 = growing, below = shrinking"),
    (('consumer confidence', 'consumer sentiment'), "how people feel about the economy"),
    (('jolts', 'job openings'), "how many jobs are open right now"),
    (('trade balance',), "exports minus imports"),
    (('crude oil inventories',), "weekly oil stock count. matters for oil and CAD"),
    (('employment change',), "change in the number of people working"),
]

CLOSERS = [
    "{moves} about to get spicy",
    "{moves} could go wild, stay sharp",
    "expect {moves} to move fast",
    "{moves} on watch. don't get caught lacking",
]


def _pick(options: List[str], key: str) -> str:
    """Stable choice: the same event always gets the same wording."""
    return options[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(options)]


def _has(value) -> bool:
    return value is not None and str(value).strip() not in ('', 'N/A', 'n/a', '-', '—')


def _when(minutes: float) -> str:
    m = int(round(minutes))
    if m <= 1:
        return "ANY MINUTE"
    if m == 60:
        return "IN 1 HOUR"
    return f"IN {m} MIN"


def _numbers(forecast, previous) -> Optional[str]:
    bits = []
    if _has(forecast):
        bits.append(f"forecast {str(forecast).strip()}")
    if _has(previous):
        bits.append(f"prev {str(previous).strip()}")
    return "  ·  ".join(bits) or None


def nickname(title: str) -> str:
    low = (title or '').lower()
    for keys, name in NICKNAMES:
        if any(k in low for k in keys):
            return name
    return (title or '').upper()


def explain(title: str) -> Optional[str]:
    """One plain sentence on what the event is, or None when it is not a known one."""
    low = (title or '').lower()
    for keys, text in EXPLAINERS:
        if any(k in low for k in keys):
            return text
    return None


def _moves(currency: str) -> str:
    name = CURRENCY_NAMES.get(currency)
    if currency == 'USD':
        return "dollar + gold"
    return name if name else f"{currency} pairs"


def compose_alert(events: List[Dict], include_emoji: bool = True) -> str:
    """One alert for events released at the same moment in the same currency.

    Each event needs: title, country, impact, time (datetime), minutes_until,
    and optionally forecast / previous.

    Layout: a loud headline, the event with its flag and time, one line on
    what it is, the numbers, then what is likely to move.
    """
    events = sorted(events, key=lambda e: str(e.get('title', '')))
    first = events[0]
    currency = first.get('country', '')
    high = any(e.get('impact') == 'High' for e in events)
    key = "|".join(str(e.get('news_id') or e.get('title')) for e in events)
    time = first['time'].strftime('%H:%M')
    when = _when(first.get('minutes_until', 0))
    region = REGION_NAMES.get(currency, currency)
    if include_emoji:
        siren, flag, chart, bolt = ("🚨" if high else "⚠️"), FLAGS.get(currency, '🌍'), "📊", "⚡"
    else:
        siren, flag, chart, bolt = ("[HIGH]" if high else "[MED]"), f"[{currency}]", "-", ">"
    lines: List[str] = []

    if len(events) == 1:
        title = str(first.get('title', '')).strip()
        lines.append(f"{siren} {nickname(title)} {when}")
        lines.append("")
        lines.append(f"{flag} {title} · {time}")
        why = explain(title)
        if why:
            lines.append(why)
        numbers = _numbers(first.get('forecast'), first.get('previous'))
        if numbers:
            lines.append("")
            lines.append(f"{chart} {numbers}")
    else:
        lines.append(f"{siren} {len(events)} {region} DROPS {when} · {time}")
        lines.append("")
        for event in events:
            title = str(event.get('title', '')).strip()
            numbers = _numbers(event.get('forecast'), event.get('previous'))
            lines.append(f"{flag} {title}")
            if numbers:
                lines.append(f"     {numbers}")

    if len(events) > 1 or not _numbers(first.get('forecast'), first.get('previous')):
        lines.append("")
    lines.append(f"{bolt} " + _pick(CLOSERS, key + "c").format(moves=_moves(currency)))
    return "\n".join(lines)


def _count_word(n: int) -> str:
    return {2: 'two', 3: 'three', 4: 'four', 5: 'five'}.get(n, str(n))


def group_events(events: List[Dict]) -> List[List[Dict]]:
    """Events of one currency released at the same minute belong in one alert."""
    groups: Dict[tuple, List[Dict]] = {}
    for event in events:
        groups.setdefault((event['time'], event.get('country', '')), []).append(event)
    return [groups[k] for k in sorted(groups, key=lambda k: (k[0], k[1]))]
