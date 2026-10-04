"""Точка входа: аргументы, защита от второго экземпляра, запуск потоков."""

import argparse
import logging
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import __version__
from . import audio, engine, gui, hotkeys, models, tray, watcher, wizard
from .config import CFG
from .constants import APP_NAME, LOCK_PORT
from .logging_setup import setup_logging
from .state import STATE, STOP

log = logging.getLogger(__name__)
_lock_sock = None


def _parse_args():
    ap = argparse.ArgumentParser(prog="meeting-transcriber",
                                 description="Автотранскрибатор конференций")
    ap.add_argument("--minimized", action="store_true",
                    help="запуститься свёрнутым в трей")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    return ap.parse_args()


def _single_instance() -> bool:
    global _lock_sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, "Приложение уже запущено (см. трей).")
        return False
    _lock_sock = s                    # держим сокет до завершения процесса
    return True


def _sd_name(idx: int) -> str:
    import sounddevice as sd
    return sd.query_devices(idx)["name"]


def main() -> None:
    args = _parse_args()
    setup_logging()
    if not _single_instance():
        return
    log.info("%s v%s запуск (python %s)", APP_NAME, __version__,
             sys.version.split()[0])

    root = tk.Tk()

    devices = audio.pick_devices(CFG)
    if not devices:
        root.withdraw()
        messagebox.showerror(APP_NAME, "Не найдено аудиоустройство для захвата.")
        return

    app = gui.App(root, args.minimized)
    tray.start()
    if args.minimized:
        tray.notify(APP_NAME, "Приложение запущено в фоновом режиме")

    seg_q: queue.Queue = queue.Queue()
    for backend, dev, tag in devices:
        if backend == "sd":
            try:
                desc = f"🎤 {_sd_name(dev)}"
            except Exception:
                desc = f"🎤 device#{dev}"
            target = audio.capture_sd
        else:
            desc = f"{'👥' if tag == 'sys' else '🎤'} {dev.name}"
            target = audio.capture_sc
        STATE.active_sources.append(desc)
        log.info("источник [%s/%s]: %s", tag, backend, desc)

        audio_q: queue.Queue = queue.Queue()      # своя очередь на канал
        threading.Thread(target=target, args=(dev, audio_q, tag),
                         daemon=True).start()
        threading.Thread(target=engine.monitor_loop,
                         args=(audio_q, seg_q, tag), daemon=True).start()

    threading.Thread(target=watcher.watcher_loop, daemon=True).start()
    threading.Thread(target=engine.transcriber_loop, args=(seg_q,),
                     daemon=True).start()
    threading.Thread(target=hotkeys.hotkey_loop, daemon=True).start()
    threading.Thread(target=models.warmup, daemon=True).start()  # модель заранее

    if not CFG.get("setup_done"):
        root.after(600, lambda: wizard.Wizard(root))

    log.info("качество=%s, автостарт=%s, триггер=%s, режим=%s",
             CFG.get("quality"), CFG.get("auto_start"),
             CFG.get("trigger"), CFG.get("source"))
    root.mainloop()
    STOP.set()
    tray.shutdown()


if __name__ == "__main__":
    main()