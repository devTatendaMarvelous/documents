"""Structured logging configuration for the Document & Image Service."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

from app.core.config import get_settings


class StructuredFormatter(logging.Formatter):
    """
    Log formatter that emits a consistent, parseable line format.

    Format::

        2026-07-22 11:00:00 | INFO | module:func:line | message | key=value ...
    """

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, self.datefmt)} | "
            f"{record.levelname} | "
            f"{record.name}:{record.funcName}:{record.lineno} | "
            f"{record.getMessage()}"
        )
        extras = getattr(record, "extra_data", None)
        if extras and isinstance(extras, dict):
            pairs = " ".join(f"{key}={value}" for key, value in extras.items())
            return f"{base} | {pairs}"
        return base


def setup_logging() -> logging.Logger:
    """
    Configure application logging to both stdout and ``logs/application.log``.

    Returns the root application logger (``documents``).
    """
    settings = get_settings()
    settings.ensure_directories()

    logger = logging.getLogger("documents")
    logger.setLevel(settings.log_level)
    logger.propagate = False

    # Avoid duplicate handlers when the app is reloaded
    if logger.handlers:
        return logger

    formatter = StructuredFormatter(datefmt="%Y-%m-%d %H:%M:%S")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(settings.log_level)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        filename=settings.log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(settings.log_level)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    # Align uvicorn / gunicorn access loggers with our level
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error"):
        third_party = logging.getLogger(name)
        third_party.setLevel(settings.log_level)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the ``documents`` namespace."""
    if name:
        return logging.getLogger(f"documents.{name}")
    return logging.getLogger("documents")


def log_extra(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    """Log a message with structured key/value fields attached."""
    logger.log(level, message, extra={"extra_data": fields})
