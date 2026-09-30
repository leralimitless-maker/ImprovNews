"""Централизованное логирование проекта ImprovNews."""
import logging
import os
import sys


class _DynamicStreamHandler(logging.Handler):
    """Хэндлер, всегда направляющий сообщения в актуальный sys.stdout
    (включая случаи перехвата stdout в тестах)."""
    def emit(self, record):
        try:
            msg = self.format(record)
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


def get_logger(name: str = "improvnews") -> logging.Logger:
    """Возвращает сконфигурированный логгер."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = _DynamicStreamHandler()
        fmt = os.environ.get("LOG_FORMAT", "%(message)s")
        handler.setFormatter(logging.Formatter(fmt))
        logger.addHandler(handler)
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, log_level, logging.INFO))
    return logger


log = get_logger()
