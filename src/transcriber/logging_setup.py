"""Логирование: файл всегда, консоль — только если есть TTY (в exe её нет)."""

import logging
import logging.handlers
import sys

from .config import data_dir


def setup_logging(level: int = logging.INFO) -> None:
    logs = data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.handlers.RotatingFileHandler(
        logs / "transcriber.log", maxBytes=2_000_000, backupCount=2,
        encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    try:
        if sys.stdout and sys.stdout.isatty():
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            root.addHandler(sh)
    except Exception:
        pass