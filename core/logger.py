import logging
import sys
import io
from logging.handlers import RotatingFileHandler
import os
from config.config_loader import get_config

LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

logging_level_str = get_config("logging_level", "ERROR").upper()
logging_level = LOG_LEVEL_MAP.get(logging_level_str, logging.ERROR)
log_file_path = get_config("LOG_FILE_PATH", "app.log")


def setup_logger(name: str):
    """Creates and configures a logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging_level)

    # Clear any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler — force UTF-8 so emoji/arrows render on Windows cp1252 terminals
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    console_handler = logging.StreamHandler(utf8_stdout)
    console_handler.setLevel(logging_level)
    console_handler.setFormatter(formatter)

    # File handler — also UTF-8 for consistent log files
    file_handler = RotatingFileHandler(log_file_path, maxBytes=1048576, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging_level)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
