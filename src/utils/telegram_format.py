"""
Shared Telegram message formatting helpers.
"""


def escape_html(text: str) -> str:
    """
    Escape special HTML characters in text to prevent parsing errors.
    For Telegram HTML mode, escape: < > &

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for HTML
    """
    if not text:
        return text

    # Convert to string if not already
    text = str(text)

    # Escape HTML special characters
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')

    return text
