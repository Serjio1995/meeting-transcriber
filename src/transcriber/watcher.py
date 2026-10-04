"""Фоновое сканирование процессов платформ ВКС."""

import logging

import psutil

from .config import CFG
from .state import STATE, STOP

log = logging.getLogger(__name__)


def scan_once(cfg: dict) -> set[str]:
    procs = [p.lower() for p in cfg["processes"]]
    brows = [p.lower() for p in cfg["browsers"]]
    found: set[str] = set()
    for p in psutil.process_iter(["name"]):
        try:
            n = (p.info.get("name") or "").lower()
        except Exception:
            continue
        if any(t in n for t in procs):
            found.add(n)
        elif cfg.get("include_browsers") and any(t in n for t in brows):
            found.add(n)
    return found


def watcher_loop() -> None:
    while not STOP.is_set():
        try:
            found = scan_once(CFG)
        except Exception as exc:
            log.error("ошибка сканирования процессов: %s", exc)
            found = set()
        with STATE.lock:
            STATE.conf_names = found
        STOP.wait(5)