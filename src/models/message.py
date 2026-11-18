"""
Message models for tracking Telegram messages
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MessageIdentifier:
    """Unique identifier for a Telegram message"""
    chat_id: str
    message_id: int
    message_hash: str
    timestamp: datetime
    
    @classmethod
    def from_telegram_event(cls, event):
        """Create MessageIdentifier from Telethon event"""
        message = event.message
        content = message.text or ""
        
        # For image-only messages content is "", so include message.id to avoid
        # all image-only messages from the same channel sharing the same hash.
        hash_input = content if content.strip() else f"__img__{message.id}"
        return cls(
            chat_id=str(message.chat_id),
            message_id=message.id,
            message_hash=str(hash(hash_input)),
            timestamp=message.date or datetime.now()
        )
    
    def get_key(self) -> str:
        """Get unique key for this message"""
        return f"{self.chat_id}:{self.message_id}"
