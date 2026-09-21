"""Structured JSON logging to stdout.

Containers log to stdout and something else does the collecting; that is the whole
contract. JSON rather than text because these lines get queried, not read.

Written by hand rather than pulled from a dependency: the requirement is about thirty
lines, and a log formatter is not where a supply chain risk is worth taking.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Attributes LogRecord always carries. Anything else was attached by the caller via
# `extra=` and is therefore worth emitting.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; route them through ours instead of
    # emitting every request twice in two different formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
