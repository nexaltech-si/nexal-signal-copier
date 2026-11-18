"""
Notification Service
Wrapper for notification sender integration
"""
from src.integrations.telegram.unified_sender import notification_sender

# Export the unified notification sender singleton
__all__ = ['notification_sender']
