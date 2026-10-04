"""Глобальные хоткеи (Windows/Linux; на macOS отключены ограничением ОС)."""

import logging
import sys
import time

from .config import CFG
from .state import STOP, ui

log = logging.getLogger(__name__)


def hotkey_loop() -> None:
    if not CFG.get("hotkeys", True):
        return
    if sys.platform == "darwin":
        log.info("macOS: глобальные хоткеи недоступны (ограничение ОС), "
                 "используйте меню трея")
        return
    try:
        import keyboard
    except ImportError:
        log.info("пакет keyboard не установлен — хоткеи отключены")
        return
    try:
        keyboard.add_hotkey("ctrl+alt+r", lambda: ui("toggle"))
        keyboard.add_hotkey("ctrl+alt+c", lambda: ui("copy"))
        log.info("хоткеи: Ctrl+Alt+R — старт/стоп | Ctrl+Alt+C — копировать всё")
        while not STOP.is_set():
            time.sleep(0.2)
    except Exception as exc:
        log.warning("хоткеи недоступны: %s", exc)