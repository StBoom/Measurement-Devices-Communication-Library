from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_dir: Path = Path("logs")) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("instrument_visa")
    logger.setLevel(logging.INFO)

    log_path = log_dir / "instrument_visa.log"
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path.resolve() for handler in logger.handlers):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)

    return logger
