"""
Split posts — one trade post delivered as several Telegram messages.

Relay channels (e.g. Discord → Telegram bridges) post a trade's TEXT first and its
chart(s) as separate caption-less photo messages 0–4 s later. Processed one by one,
the chart is a second, unrelated "signal": with vision on it was auto-executed as
a duplicate of the text's trade, with TPs the vision model invented from 1:1/1:2 RR.

The tracker links a caption-less photo to the text posted just before it in the
same chat by the same sender, and tells the handler what that text became:

  extracted     the text produced a signal  → attach the chart to it as evidence
  needs_image   the text was a trade but lacked levels a chart can supply
                → re-run extraction on text + chart together (real fusion)
  neither       command / status / commentary → the chart is just illustration

Pure bookkeeping with Telegram timestamps, so the live MessageHandler and the
simulator share the exact same decisions.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

# Observed relay gap: text → its images within 0–4 s. 8 s leaves headroom without
# swallowing an unrelated chart posted later.
SPLIT_POST_WINDOW_S = 8.0

# IntegratedProcessor rejection reasons that mean "a chart would have completed this"
_NEEDS_IMAGE_MARKERS = (
    "no chart image to extract from",
    "no vision ai key configured",
    "vision ai could not extract",
)


@dataclass
class TextPost:
    chat: str
    sender: Optional[str]
    message_id: int
    text: str
    ts: datetime
    extracted: bool = False
    needs_image: bool = False
    fused: bool = False          # a chart already re-ran extraction for this post
    done: asyncio.Event = field(default_factory=asyncio.Event)


class SplitPostTracker:
    def __init__(self, window_s: float = SPLIT_POST_WINDOW_S):
        self.window_s = window_s
        self._last: Dict[Tuple[str, Optional[str]], TextPost] = {}
        self._by_msg: Dict[Tuple[str, int], TextPost] = {}

    @staticmethod
    def is_companion_candidate(text: str, has_image: bool, grouped_id, is_reply: bool) -> bool:
        """A bare chart: image, no caption, not part of an album, not a reply."""
        return bool(has_image and not (text or "").strip() and not grouped_id and not is_reply)

    def start_text(self, chat, sender, message_id: int, text: str, ts: datetime) -> TextPost:
        post = TextPost(str(chat), str(sender) if sender is not None else None, message_id, text, ts)
        self._last[(post.chat, post.sender)] = post
        self._by_msg[(post.chat, message_id)] = post
        if len(self._by_msg) > 500:  # bounded memory
            for k in list(self._by_msg)[:250]:
                self._by_msg.pop(k, None)
        return post

    def note_extraction(self, chat, message_id: int, extracted: bool, rejection: Optional[str]) -> None:
        post = self._by_msg.get((str(chat), message_id))
        if not post:
            return
        post.extracted = post.extracted or extracted
        reason = (rejection or "").lower()
        post.needs_image = not post.extracted and any(m in reason for m in _NEEDS_IMAGE_MARKERS)

    @staticmethod
    def finish(post: TextPost) -> None:
        post.done.set()

    def companion_for(self, chat, sender, ts: datetime) -> Optional[TextPost]:
        post = self._last.get((str(chat), str(sender) if sender is not None else None))
        if not post or ts is None or post.ts is None:
            return None
        gap = (ts - post.ts).total_seconds()
        return post if 0 <= gap <= self.window_s else None
