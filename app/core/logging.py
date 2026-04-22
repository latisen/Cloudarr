"""Structured logging configuration."""

import logging
import sys

from pythonjsonlogger import jsonlogger


def configure_logging(level: str) -> None:
    """Configure root logger for JSON structured logs."""

    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(level.upper())

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(job_id)s %(state)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
