"""
Deterministic checks for the NEW-SIGNAL path.

The extraction AI occasionally reads a provider's results recap that repeats the
original levels ("XAUUSD BUY 4100 SL 4090 ✅ TP1 hit +200 pips") as a fresh setup,
or a "no entry for me / waiting confirmation" caption + chart as a new trade.
IntegratedProcessor uses these after extraction to reject or require manual
approval — never to open more.

Reply/command handling is deliberately NOT gated here: the reply AI decides
from the message, thread history and live account state.
"""
import re
from typing import Optional

# Provider reporting what already happened — results, progress, celebration.
_STATUS_REPORT_PATTERNS = [
    r'\+\s*\d+(?:\.\d+)?\s*pips?\b',                                   # "+150 pips"
    r'\b\d+(?:\.\d+)?\s*pips?\s+(?:running|done|secured|booked|smashed|again|in\s+profit|profit|hit|closed)\b',
    r'\bpips?\s+running\b',                                             # "150 pips running"
    r'\brunning\s+\+?\d+',                                              # "running +50"
    r'\b(?:tp|target)s?[\s_-]*\d*[\s_-]*(?:hit|smashed|smacked|done|reached|achieved)\b',
    r'\b(?:hit|smashed|smacked)\s+(?:the\s+)?(?:tp|target)',
    r'\bprofits?\s+(?:secured|booked|locked|banked|taken)\b',           # "Profit Secured"
    r'\b(?:secured|booked|banked|locked)\s+(?:the\s+|maximum\s+|max\s+|all\s+)*(?:profits?|gains?)\b',
    r'\bdeal\s+done\b',
    r'\btrade\s+(?:completed|closed|done|finished)\b',
    r'\bback[\s_-]*to[\s_-]*back\b',
    r'\bzero\s+float\b',
]
_STATUS_REPORT_RE = re.compile('|'.join(_STATUS_REPORT_PATTERNS), re.IGNORECASE)

# Explicit instruction to followers. Base verb forms only — "booked"/"secured"/
# "closed" are past-tense reports and deliberately do not match.
_IMPERATIVE_PATTERNS = [
    r'\b(?:close|exit|cancel|move|modify|cut|secure|book|bank|lock|reduce|trail|partial)\b',
    r'\btake\s+(?:some\s+|more\s+|partial\s+|half\s+)*(?:profits?|partials?|\d+\s*%)',
    r'\bget\s+out\b',
    r'\bset\s+(?:be|sl|tp|stop)\b',
    r'\bbreak\s*-?\s*even\b',
    r'\b(?:can|now)\s+be\b|\bbe\s+now\b',                               # "can BE now"
    r'\bsl\s+to\b',                                                     # "SL to entry"
]
_IMPERATIVE_RE = re.compile('|'.join(_IMPERATIVE_PATTERNS), re.IGNORECASE)

# Caption explicitly says not to enter (yet).
_NO_ENTRY_PATTERNS = [
    r'\bno\s+entry\b',
    r"\b(?:don'?t|do\s+not|dont)\s+(?:enter|take|jump|rush)\b",
    r'\bnot\s+(?:entering|taking\s+(?:it|this)|a\s+signal)\b',
    r'\bwait(?:ing)?\s+(?:for\s+)?(?:the\s+)?confirmation\b',
    r'\b(?:what\s+i\s*(?:am|\'m)\s+|just\s+)watching\b',
    r'\bno\s+trade\b',
    r'\beducational\b|\bfor\s+education\b',
]
_NO_ENTRY_RE = re.compile('|'.join(_NO_ENTRY_PATTERNS), re.IGNORECASE)


_BREAKEVEN_WORDING_RE = re.compile(
    r'(?i:break\s*-?\s*even|risk\s*free|sl\s+to\s+(?:entry|be|b\.e)|move\s+(?:the\s+|your\s+)?(?:sl|stop)'
    r'|stop\s+to\s+entry|set\s+b\.?e|\bbe\s+(?:set|taken|now)\b|\bcan\s+be\s+now\b|\b(?:new|update[ds]?)\s+sl\b|\bsl\s+updated\b)'
    r'|\bB\.?E\b',  # uppercase "BE" / "B.E" only — lowercase "be" is the ordinary verb
)

_STRICT_BREAKEVEN_RE = re.compile(
    r'(?i:\bbreak[\s-]?even\b|\brisk[\s-]?free\b|\bset\s+b\.?e\b|\bmove\s+to\s+b\.?e\b'
    r'|\bsl\s+to\s+(?:be|b\.e|entry)\b|\bstop\s+to\s+entry\b|\bbe\s+now\b|\bcan\s+be\s+now\b)'
    r'|\bB\.?E\b',  # uppercase "BE" / "B.E" only - lowercase "be" is the ordinary verb
)


def has_breakeven_wording(text: str) -> bool:
    """
    True for explicit break-even wording ("breakeven", "risk free", "SL to entry", "set BE", uppercase "BE").
    Whole-word on purpose: substring tests on ' be' / 'be ' matched "better", "below", "because",
    "before" and moved stop-losses to entry on ordinary commentary. Deliberately narrower than
    _BREAKEVEN_WORDING_RE: "move SL"/"new SL" are price modifications, not break-even.
    """
    return bool(text) and bool(_STRICT_BREAKEVEN_RE.search(text))


def looks_like_status_report(text: str) -> bool:
    """True when the text reports results/progress (pips running, TP hit, profit secured)."""
    return bool(text) and bool(_STATUS_REPORT_RE.search(text))


def has_trade_instruction(text: str) -> bool:
    """True when the text contains an explicit instruction to act on a trade."""
    return bool(text) and bool(_IMPERATIVE_RE.search(text) or _BREAKEVEN_WORDING_RE.search(text))


def is_status_not_command(text: str) -> bool:
    """
    A results/progress report with no explicit instruction to act.
    Such a message must never close, modify, or open a trade.
    """
    return looks_like_status_report(text) and not has_trade_instruction(text)


# A legal disclaimer under a post ("⚠️ DISCLAIMER: ... for educational purposes only. Not
# financial advice ...") is boilerplate on every post of the channel, not the author saying
# "don't take this one". It is left out before looking for no-entry wording.
_DISCLAIMER_BLOCK_RE = re.compile(r'\bdisclaimer\b\s*[:\-–—].*\Z', re.IGNORECASE | re.DOTALL)
_DISCLAIMER_SENTENCE_RE = re.compile(
    r'[^.!?\n]*\b(?:not\s+(?:a\s+)?(?:financial|investment)\s+advice|(?:financial|investment)\s+advis[eo]rs?)\b[^.!?\n]*[.!?]?',
    re.IGNORECASE)
_EDUCATIONAL_PURPOSES_RE = re.compile(r'\bfor\s+educational\s+purposes(?:\s+only)?\b', re.IGNORECASE)


def without_disclaimer(text: str) -> str:
    """The post without its legal disclaimer."""
    had_advice_notice = bool(_DISCLAIMER_SENTENCE_RE.search(text))
    text = _DISCLAIMER_BLOCK_RE.sub('', text)
    text = _DISCLAIMER_SENTENCE_RE.sub('', text)
    if had_advice_notice:   # "for educational purposes only" next to "not financial advice"
        text = _EDUCATIONAL_PURPOSES_RE.sub('', text)
    return text


def negates_entry(text: str) -> bool:
    """True when the caption says not to enter / to wait ("no entry for me", "waiting confirmation")."""
    return bool(text) and bool(_NO_ENTRY_RE.search(without_disclaimer(text)))


# ── Instant ("NOW") entry wording ─────────────────────────────────────────────
DEFAULT_INSTANT_KEYWORDS = ('now', 'instant', 'market', 'immediately', 'asap')

# A keyword only counts when it is part of the entry instruction: within a few
# words of a direction/entry word or a price ("SELL GOLD NOW", "NOW @ 4115",
# "buy at market"). Keeps "market analysis…" / "now we wait…" commentary out.
_ENTRY_CONTEXT_RE = re.compile(
    r"^(?:buy|sell|long|short|enter|entry|execute|open|@|\d+(?:[.,]\d+)?)$", re.IGNORECASE)
_NEGATION_TOKENS = {'not', "don't", 'dont', 'do not', 'no', 'never', 'avoid', 'wait', "isn't", 'without'}
_TOKEN_RE = re.compile(r"[a-z]+'[a-z]+|[^\W_]+(?:[.,]\d+)?|@", re.IGNORECASE)
_CONTEXT_WINDOW = 3


def find_instant_keyword(text: str, keywords=None) -> Optional[str]:
    """
    Return the keyword that marks this message as an instant ("enter now") entry,
    or None. Whole words only ("know"/"unknown" never match "now"), skips negated
    uses ("not now", "don't buy now"), and requires entry context nearby.
    Multi-word keywords ("at market") are matched as a phrase.
    """
    if not text:
        return None
    kws = [str(k).strip().lower() for k in (keywords or DEFAULT_INSTANT_KEYWORDS) if str(k).strip()]
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    for kw in kws:
        kw_tokens = _TOKEN_RE.findall(kw)
        n = len(kw_tokens)
        if not n:
            continue
        for i in range(len(tokens) - n + 1):
            if tokens[i:i + n] != kw_tokens:
                continue
            before = tokens[max(0, i - 2):i]
            if any(t in _NEGATION_TOKENS for t in before) or ' '.join(before) in _NEGATION_TOKENS:
                continue
            window = tokens[max(0, i - _CONTEXT_WINDOW):i] + tokens[i + n:i + n + _CONTEXT_WINDOW]
            if any(_ENTRY_CONTEXT_RE.match(t) for t in window):
                return kw
    return None


# A message that is nothing but a take-profit level: "Tp1 : 3858", "TP 3858", "New TP2 = 3835".
# Anything after the price ("TP1 3858 hit ✅", "TP 30 pips") makes it a report, not a level.
_BARE_TP_LEVEL_RE = re.compile(
    r'^\W*(?:new\s+)?(?:tp|take\s*profit|target)\s*(?:(\d)(?=\s*[:=@>\-–—]|\s))?\s*[:=@>\-–—]*\s*(?:to\s+|at\s+|now\s+)?'
    r'(\d{2,}(?:[.,]\d+)?)\W*$',
    re.IGNORECASE,
)


def bare_tp_level(text: str):
    """
    (tp number or None, price) when the whole message is a take-profit level the
    channel sets for its running trade — e.g. "Tp1 : 3858" → (1, 3858.0). None otherwise.
    """
    m = _BARE_TP_LEVEL_RE.match(text or '')
    if not m:
        return None
    return (int(m.group(1)) if m.group(1) else None), float(m.group(2).replace(',', '.'))


# The channel leaves it to the follower to take part of the profit: "Can booked some",
# "You can book some profits", "u can secure some now", "Close some ok stay safe".
# A report of what the provider did ("Booked some profits", "Closed some here") has
# neither "can" nor the imperative "close some" and is not matched; nor is "don't close some".
_OPTIONAL_PARTIAL_RE = re.compile(
    r'\b(?:can|could|may)\s+(?:now\s+)?(?:book(?:ed)?|secure|take|close)\s+some\b'
    r"|(?<!n't )(?<!not )(?<!never )\bclose\s+some\b",
    re.IGNORECASE,
)


def offers_partial_profit(text: str) -> bool:
    """True for "Can booked some" and the like: take half off, where a position can be split."""
    return bool(text) and bool(_OPTIONAL_PARTIAL_RE.search(text))

