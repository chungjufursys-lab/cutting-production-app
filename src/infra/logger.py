import logging
from pathlib import Path


def setup_logger(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("cutting_app")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        log_file.parent.mkdir(parents=True, exist_ok=True)

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)

        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger