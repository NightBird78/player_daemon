import logging
import sys


def setup_logger(
    name: str,
    level: int = logging.INFO,
    format_string: str = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    if format_string is None:
        format_string = "%(levelname)-8s | %(name)s:%(lineno)d | %(message)s"

    formatter = logging.Formatter(format_string)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
