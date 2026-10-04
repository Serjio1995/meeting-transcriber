"""Общее состояние между потоками + очередь событий для GUI."""

import queue
import threading
import time


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.conf_names: set[str] = set()      # совпавшие процессы ВКС
        self.recording = False
        self.trigger_kind: str | None = None   # proc | sound | manual
        self.session_file: str | None = None
        self.cooldown_until = 0.0
        self.model_loading = False
        self.audio_ok = True
        self.blackhole_hint = False            # macOS: BlackHole не найден
        self.last_speech = time.time()         # речь в ЛЮБОМ канале (автостоп)
        self.manual_stop_gen = 0               # счётчик команд ручной остановки
        self.levels = {"sys": 0.0, "mic": 0.0} # текущий RMS каждого канала
        self.active_sources: list[str] = []    # что реально захвачено
        self.last_download: dict = {}          # последний прогресс загрузки модели


STATE = State()
UI_Q: "queue.Queue" = queue.Queue()
STOP = threading.Event()


def ui(kind: str, data=None) -> None:
    """Потокобезопасная отправка события в GUI."""
    UI_Q.put((kind, data))