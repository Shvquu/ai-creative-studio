"""Logging setup: rotating file log in data/logs plus console output.

The MCP server uses stdio for protocol messages, therefore console logging
always goes to **stderr**, never stdout.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured: set[str] = set()


def setup_logging(
    logs_dir: Path,
    level: str = "INFO",
    filename: str = "studio.log",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
    console: bool = True,
) -> None:
    key = str(logs_dir / filename)
    if key in _configured:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level.upper())
    formatter = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        logs_dir / filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console and not any(getattr(h, "_acs_console", False) for h in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream._acs_console = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    # Quiet noisy libraries.
    for noisy in ("httpx", "httpcore", "websockets", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured.add(key)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
