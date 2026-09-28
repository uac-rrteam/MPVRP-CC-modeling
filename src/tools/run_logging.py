"""Configure console and per-run file logging for tool commands."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from loguru import logger

from paths import RESULTS_DIR

DEFAULT_LOG_DIR = RESULTS_DIR / "logs"


def configure_run_logging(
    command: str,
    *,
    verbose: bool = False,
    quiet: bool = False,
    log_dir: Path | None = None,
) -> Path:
    """Start a fresh log file and return its path."""
    directory = log_dir or DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{command}_{timestamp}_{uuid4().hex[:8]}.log"

    logger.remove()
    console_level = "WARNING" if quiet else "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=console_level, format="{level}: {message}")
    logger.add(
        path,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS Z} | {level:<8} | {name}:{function}:{line} | {message}",
        backtrace=True,
        diagnose=False,
    )
    logger.info("Run started: {} (log: {})", command, path)
    return path
