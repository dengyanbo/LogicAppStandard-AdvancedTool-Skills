"""Centralized logging configuration.

The CLI configures a single rich-formatted root logger; modules use
`logging.getLogger(__name__)`.
"""
from __future__ import annotations

import logging
import os

from rich.logging import RichHandler


def configure(level: str | None = None) -> None:
    lvl = (level or os.environ.get("LAT_LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=lvl,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    # Silence noisy Azure SDK debug logging by default.
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
