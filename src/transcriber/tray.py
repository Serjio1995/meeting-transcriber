"""Системный трей (pystray): иконка-индикатор, меню, уведомления."""

import logging
import threading

import pystray
from PIL import Image, ImageDraw

from . import models
from .config import CFG, save_config
from .constants import APP_NAME, STATUS_COLORS
from .state import STATE, ui

log = logging.getLogger(__name__)
ICON = None


def tray_image(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, 58, 58], fill=color)
    d.ellipse([24, 16, 40, 36], fill="white")        # капсула микрофона
    d.rectangle([29, 34, 35, 45], fill="white")
    d.arc([20, 26, 44, 50], 0, 180, fill="white", width=3)
    return img


def _toggle_label(item) -> str:
    return "⏹ Остановить запись" if STATE.recording else "▶ Начать запись вручную"


def _menu() -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem("Показать окно", lambda i, it: ui("show"), default=True),
        pystray.MenuItem("🧙 Мастер настройки", lambda i, it: ui("wizard")),
        pystray.MenuItem(_toggle_label, lambda i, it: ui("toggle")),
        pystray.MenuItem("📋 Копировать весь текст", lambda i, it: ui("copy")),
        pystray.MenuItem(
            "Автостарт по конференции",
            lambda i, it: (CFG.__setitem__("auto_start", not CFG["auto_start"]),
                           save_config()),
            checked=lambda it: CFG.get("auto_start", True)),
        pystray.MenuItem(
            "🔥 Прогреть модель",
            lambda i, it: threading.Thread(target=models.warmup,
                                           daemon=True).start()),
        pystray.MenuItem("Выход", lambda i, it: ui("exit")),
    )


def start() -> None:
    global ICON
    ICON = pystray.Icon("transcriber", tray_image(STATUS_COLORS["idle"]),
                        APP_NAME, _menu())
    try:
        ICON.run_detached()          # macOS требует main thread для tkinter
    except Exception as exc:
        log.warning("run_detached недоступен (%s) — запускаю в потоке", exc)
        threading.Thread(target=ICON.run, daemon=True).start()


def set_color(color: str) -> None:
    if ICON is not None:
        try:
            ICON.icon = tray_image(color)
        except Exception:
            pass


def notify(title: str, msg: str) -> None:
    if ICON is not None:
        try:
            ICON.notify(msg, title)
        except Exception:
            pass


def shutdown() -> None:
    if ICON is not None:
        try:
            ICON.stop()
        except Exception:
            pass