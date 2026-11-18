"""
Symbol Matcher Service

When a chart screenshot gives us a clean setup — direction, entry, SL, TP — but
no readable ticker, the price levels themselves are the strongest clue we have:
only a handful of the broker's instruments actually trade around 3350, or around
1.0834, or around 43120.

This service asks the broker for a snapshot of every symbol and its current
quote, then ranks the ones whose live price brackets the signal's levels. Those
become the buttons on the "which instrument is this?" prompt instead of a fixed
hard-coded list, so the user is offered real, tradable candidates.

It also handles the reverse direction: taking whatever ticker the user typed
(`/symbol GOLD`) and mapping it onto a symbol the broker actually quotes,
with near-miss suggestions when it doesn't match.
"""
import asyncio
import re
from typing import Dict, List, Optional, Sequence, Tuple

from loguru import logger

from src.utils.symbols import normalize_symbol

# Brokers bolt noise onto instrument names — EURUSD.m, XAUUSD+, US30.cash,
# GER40-ecn — so strip it down before comparing like with like.
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")
_BROKER_TAGS = ("MICRO", "CASH", "ECN", "PRO", "RAW", "STD", "SB", "FX")


def _canonical(name: str) -> str:
    """'EURUSD.m' / 'EURUSD_i' / 'eurusd+' → 'EURUSD' (best effort)."""
    if not name:
        return ""
    upper = str(name).upper().strip()
    stripped = _NON_ALNUM_RE.sub("", upper)
    # Drop a trailing broker tag when what's left still looks like an instrument
    for tag in _BROKER_TAGS:
        if stripped.endswith(tag) and len(stripped) - len(tag) >= 3:
            stripped = stripped[: -len(tag)]
            break
    if len(stripped) > 6 and stripped[:6].isalpha() and stripped[6:].isalnum():
        # EURUSDM, EURUSDI → EURUSD (only when the base is a plausible pair)
        if len(stripped) - 6 <= 2:
            stripped = stripped[:6]
    return stripped


def _decimals(value: float) -> int:
    """How many decimal places a quoted price is carrying (2 for 3350.25)."""
    try:
        text = f"{float(value):.10f}".rstrip("0")
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1])
    except (TypeError, ValueError):
        return 0


def _mid(row: dict) -> float:
    """Mid price from a quote row, tolerating one-sided or missing quotes."""
    try:
        bid = float(row.get("bid") or 0)
        ask = float(row.get("ask") or 0)
    except (TypeError, ValueError):
        return 0.0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return bid or ask


class SymbolMatcherService:
    # Widening search bands: try to find something tight before casting around.
    TOLERANCE_STEPS = (0.005, 0.02, 0.08, 0.25)
    # A chart's SL/TP normally sit within this much of price; further out and
    # the match is probably a coincidence of magnitude.
    MAX_LEVEL_SPREAD = 0.35

    def _preferred(self) -> List[str]:
        """Canonical instruments we'd rather offer, from VISION_ALLOWED_SYMBOLS."""
        from config.settings import settings

        raw = getattr(
            settings, "vision_allowed_symbols",
            "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,US30,NAS100,SPX500,"
            "GBPJPY,USDCAD,AUDUSD,NZDUSD,USDCHF,EURJPY,EURGBP",
        )
        return [s.strip().upper() for s in str(raw).split(",") if s.strip()]

    async def _snapshot(self) -> List[dict]:
        """Every broker symbol with its quote (empty list if unavailable)."""
        try:
            from src.services.trading_service import trading_service

            provider = trading_service.trading_provider
            if not provider:
                return []
            rows = await provider.get_symbols_snapshot()
            return rows or []
        except Exception as e:
            logger.warning(f"Symbol matcher: could not fetch symbol snapshot — {e}")
            return []

    async def _price_shortlist(self, names: Sequence[str]) -> List[dict]:
        """
        Fallback when the broker can't dump quotes in bulk: price the preferred
        instruments one by one, with a little concurrency.
        """
        try:
            from src.services.trading_service import trading_service

            provider = trading_service.trading_provider
            if not provider:
                return []
        except Exception:
            return []

        sem = asyncio.Semaphore(5)

        async def one(name: str) -> Optional[dict]:
            async with sem:
                try:
                    price = await asyncio.wait_for(provider.get_symbol_price(name), timeout=10)
                except Exception:
                    return None
                if not price:
                    return None
                return {"name": name, "bid": price.get("bid", 0), "ask": price.get("ask", 0)}

        results = await asyncio.gather(*(one(n) for n in names), return_exceptions=True)
        return [r for r in results if isinstance(r, dict) and _mid(r) > 0]

    # ── Ranking ──────────────────────────────────────────────────────────

    def _score(
        self,
        row: dict,
        reference: float,
        levels: Sequence[float],
        tolerance: float,
        preferred: Sequence[str],
    ) -> Optional[Tuple[float, float]]:
        """(score, relative distance) for one symbol, or None if out of range."""
        price = _mid(row)
        if price <= 0 or reference <= 0:
            return None

        # MT5 trade_mode 0 = trading disabled for this instrument
        if row.get("trade_mode") == 0:
            return None

        rel = abs(price - reference) / reference
        if rel > tolerance:
            return None

        # Every level on the chart should sit near this instrument's price —
        # an SL 80% away means we matched on magnitude alone.
        spread = max((abs(lvl - price) / price for lvl in levels if lvl), default=0.0)
        if spread > self.MAX_LEVEL_SPREAD:
            return None

        score = 100.0 * (1.0 - rel / tolerance)
        score += 25.0 * (1.0 - min(spread / self.MAX_LEVEL_SPREAD, 1.0))

        # Quote precision is a strong tell: 1.08345 is a 5-digit pair, 3350.25
        # is a 2-digit metal/index.
        digits = row.get("digits")
        if isinstance(digits, (int, float)):
            gap = abs(int(digits) - _decimals(reference))
            if gap == 0:
                score += 30.0
            elif gap == 1:
                score += 15.0
            elif gap >= 3:
                score -= 15.0

        canon = _canonical(row.get("name", ""))
        if canon in preferred:
            score += 40.0
        if row.get("visible"):
            score += 5.0
        # Prefer the plain name over a broker variant of the same instrument
        score -= 2.0 * max(0, len(_NON_ALNUM_RE.sub("", str(row.get("name", "")).upper())) - len(canon))

        return score, rel

    async def find_by_price(
        self,
        levels: Sequence[Optional[float]],
        limit: int = 8,
    ) -> List[Dict]:
        """
        Rank broker symbols whose live price sits in the same range as `levels`.

        `levels` is the signal's price levels — entry first, then SL/TPs. The
        first non-empty value anchors the search; the rest are used as a sanity
        check on the match.

        Returns up to `limit` dicts: {symbol, price, distance_pct, score},
        best first. Empty when there's no price to search on or the broker
        can't be reached.
        """
        clean = [float(l) for l in levels if l not in (None, "") and float(l or 0) > 0]
        if not clean:
            return []

        reference = clean[0]
        preferred = self._preferred()

        rows = await self._snapshot()
        if not any(_mid(r) > 0 for r in rows):
            # No bulk quotes — price the instruments we care about most instead.
            names = [r.get("name") for r in rows if _canonical(r.get("name", "")) in preferred]
            rows = await self._price_shortlist(names or preferred)

        if not rows:
            logger.warning("Symbol matcher: no quotes available from the broker")
            return []

        for tolerance in self.TOLERANCE_STEPS:
            scored = []
            for row in rows:
                result = self._score(row, reference, clean, tolerance, preferred)
                if result:
                    score, rel = result
                    scored.append({
                        "symbol": row.get("name"),
                        "price": _mid(row),
                        "distance_pct": rel * 100,
                        "score": score,
                    })
            if not scored:
                continue

            # One button per instrument — collapse EURUSD / EURUSD.m / EURUSDm
            best_per_instrument: Dict[str, dict] = {}
            for item in sorted(scored, key=lambda x: -x["score"]):
                key = _canonical(item["symbol"])
                if key not in best_per_instrument:
                    best_per_instrument[key] = item

            ranked = sorted(best_per_instrument.values(), key=lambda x: -x["score"])[:limit]
            logger.info(
                f"🔎 Symbol matcher: {len(ranked)} candidate(s) trading near {reference} "
                f"(±{tolerance * 100:.1f}%): {', '.join(c['symbol'] for c in ranked)}"
            )
            return ranked

        logger.info(f"🔎 Symbol matcher: nothing trades near {reference} on this account")
        return []

    # ── User-typed ticker → broker symbol ────────────────────────────────

    async def resolve_user_symbol(self, text: str) -> Tuple[Optional[str], List[str]]:
        """
        Map whatever the user typed onto a symbol the broker actually quotes.

        Returns (broker_symbol, suggestions). On a miss, broker_symbol is None
        and suggestions holds near matches to show them.
        """
        raw = (text or "").strip().upper()
        if not raw:
            return None, []

        candidates = [raw, normalize_symbol(raw), _canonical(raw)]
        seen_candidates = []
        for c in candidates:
            if c and c not in seen_candidates:
                seen_candidates.append(c)

        rows = await self._snapshot()
        names = [r.get("name") for r in rows if r.get("name")]

        if not names:
            # Can't verify against the broker — let the trading provider try.
            try:
                from src.services.trading_service import trading_service

                provider = trading_service.trading_provider
                if provider:
                    resolved = await provider.resolve_symbol(seen_candidates[0])
                    return resolved, []
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")
            return seen_candidates[0], []

        upper_map = {str(n).upper(): n for n in names}
        canon_map: Dict[str, List[str]] = {}
        for n in names:
            canon_map.setdefault(_canonical(n), []).append(n)

        # 1. Exact name, 2. alias-normalized name, 3. same instrument, broker variant
        for cand in seen_candidates:
            if cand in upper_map:
                return upper_map[cand], []
        for cand in seen_candidates:
            variants = canon_map.get(_canonical(cand))
            if variants:
                return sorted(variants, key=len)[0], []

        # Near misses — anything containing what they typed, then progressively
        # shorter prefixes (XAUEUR → XAU… → XAUUSD)
        needle = seen_candidates[0]
        suggestions = [n for n in names if needle in str(n).upper()][:8]
        for size in (4, 3):
            if suggestions or len(needle) < size:
                break
            suggestions = [n for n in names if str(n).upper().startswith(needle[:size])][:8]
        return None, suggestions


symbol_matcher_service = SymbolMatcherService()
