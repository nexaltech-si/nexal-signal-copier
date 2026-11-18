"""
Message ids for the extra trades of a multi-signal post.

The database allows one signal per (channel, message id) and the magic number derives from the id, so the 2nd..4th
trade of one Telegram post get synthetic ids. They live in their own negative range (<= -SPLIT_BASE) so they can never
collide with real message ids (positive) or with the continuation/top-up ids (-<message id>, small negatives).
"""
SPLIT_BASE = 1_000_000_000
MAX_SPLIT_INDEX = 3


def split_message_id(original_id: int, index: int) -> int:
    """Synthetic id of trade `index` (1..3) of the post `original_id`."""
    return -(SPLIT_BASE + abs(int(original_id)) * 10 + int(index))


def is_split_id(message_id: int) -> bool:
    return int(message_id) <= -SPLIT_BASE


def real_message_id(message_id: int) -> int:
    """The Telegram message a (possibly synthetic) id belongs to."""
    mid = int(message_id)
    if mid <= -SPLIT_BASE:
        return (abs(mid) - SPLIT_BASE) // 10
    return mid


def sibling_ids(original_id: int) -> list:
    """Ids the extra trades of post `original_id` would have."""
    return [split_message_id(original_id, i) for i in range(1, MAX_SPLIT_INDEX + 1)]
