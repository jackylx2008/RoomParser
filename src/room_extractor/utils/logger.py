from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from logging_config import get_logger, setup_logger
except ModuleNotFoundError:
    PROJECT_ROOT = Path.cwd()

    def setup_logger(
        log_level: int | str = logging.INFO,
        log_file: str | None = None,
        filemode: str = "w",
    ) -> logging.Logger:
        """Fallback logger used when root logging_config.py is not importable."""
        if log_file is None:
            main_module = Path(sys.argv[0]).stem or "app"
            log_file = str(PROJECT_ROOT / "log" / f"{main_module}.log")

        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        root_logger = logging.getLogger()
        root_logger.setLevel(_coerce_log_level(log_level))
        root_logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(module)s - %(message)s")
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        file_handler = RotatingFileHandler(
            log_path,
            mode=filemode,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)
        return root_logger

    def get_logger(name: str | None = None) -> logging.Logger:
        """Return a logger under the fallback logging configuration."""
        return logging.getLogger(name)

    def _coerce_log_level(log_level: int | str) -> int:
        if isinstance(log_level, str):
            level = logging.getLevelName(log_level.upper())
            if isinstance(level, int):
                return level
            raise ValueError(f"Unknown log level: {log_level}")
        return log_level

