"""Structured logging configuration."""

import logging
import sys

from pythonjsonlogger import jsonlogger


class _ContextDefaultsFilter(logging.Filter):
    """Ensure structured log fields always exist to avoid formatter key errors."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "job_id"):
            record.job_id = "-"
        if not hasattr(record, "state"):
            record.state = "-"
        return True


def configure_logging(level: str) -> None:
    """Configure root logger for JSON structured logs."""

    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(level.upper())

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(_ContextDefaultsFilter())
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(job_id)s %(state)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
