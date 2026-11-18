"""
Logging configuration helper.

Kept in config/ so both main.py and settings.py can import it
without creating a circular dependency.
"""
import sys
from loguru import logger


def configure_logging(settings) -> None:
    """
    (Re-)configure loguru sinks from the current settings values.

    Called once at startup and again whenever LOG_LEVEL / LOG_FILE_LEVEL /
    LOG_FILE_DEBUG change via the hot-reload path in settings.reload_from_db().
    """
    logger.remove()

    # Terminal sink
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level=settings.log_level,
    )

    # File sink — priority: log_file_debug > log_file_level > log_level
    if settings.log_file_debug:
        file_log_level = "DEBUG"
    elif settings.log_file_level:
        file_log_level = settings.log_file_level
    else:
        file_log_level = settings.log_level

    logger.add(
        "logs/trading_bot_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        # Auto-clean: daily files older than a week are deleted at rotation.
        retention="7 days",
        level=file_log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
    )

    if file_log_level == "DEBUG":
        logger.info("📝 File logging level: DEBUG (verbose mode enabled)")
    else:
        logger.debug(f"📝 File logging level: {file_log_level}")
