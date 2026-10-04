"""Оркестратор: сессии, сборка фраз по каналам, запись и распознавание."""

import logging
import queue
import time
from collections import deque
from datetime import datetime

import numpy as np

from . import asr
from .config import CFG, TRANSCRIPT_DIR
from .constants import (CHUNK_MS, PREBUF_MS, SEG_MAX_MS, SEG_MIN_MS,
                        SEG_SILENCE_MS, SUSTAINED_MIN, SUSTAINED_WIN,
                        TAG_MIC, TAG_SYS)
from .state import STATE, STOP, ui
from .vad import AdaptiveVAD

log = logging.getLogger(__name__)

TAGS = {TAG_SYS: "👥 Участники", TAG_MIC: "🎤 Я"}
_STOP_REASONS = {"silence": "тишина", "proc": "конференция завершена",
                 "manual": "остановлено вручную"}

# Защита от мусорных сегментов (шум VAD усиливает вместе с речью):
_START_DEBOUNCE = 3        # подряд «речевых» кадров (300 мс), чтобы открыть фразу
_MIN_SPEECH_FRAMES = 5     # минимум речевых кадров во фразе, иначе не отправляем


def _begin_session(kind: str) -> None:
    """Создаёт файл сессии. Вызывать ТОЛЬКО под STATE.lock."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    fname = TRANSCRIPT_DIR / f"meeting_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt"
    STATE.recording = True
    STATE.trigger_kind = kind
    STATE.session_file = str(fname)
    STATE.last_speech = time.time()
    try:
        with open(fname, "a", encoding="utf-8") as fh:
            fh.write(f"=== Конференция {datetime.now():%d.%m.%Y %H:%M} ===\n")
    except OSError as exc:
        log.error("не создать файл транскрипта: %s", exc)
    ui("header", f"─── Конференция начата: {datetime.now():%H:%M} ───")
    ui("file", str(fname))
    ui("notify", ("Транскрибатор", "🎙 Конференция обнаружена — записываю"))
    log.info("старт сессии (%s): %s", kind, fname)


def start_recording(kind: str) -> None:
    with STATE.lock:
        if STATE.recording:
            return                      # сессия уже открыта другим каналом
        _begin_session(kind)


def stop_recording(reason: str) -> None:
    with STATE.lock:
        if not STATE.recording:
            return                      # уже остановлено другим каналом
        STATE.recording = False
        STATE.trigger_kind = None
        STATE.cooldown_until = time.time() + 30   # антидребезг перезапуска
    ui("notify", ("Транскрибатор",
                  f"⏹ Запись остановлена ({_STOP_REASONS.get(reason, reason)})"))
    log.info("стоп сессии: %s", reason)


def request_manual_stop() -> None:
    """Атомарная команда «стоп» для всех каналов (без гонок по событиям)."""
    with STATE.lock:
        STATE.manual_stop_gen += 1


def _flush(seg, seg_q, tag):
    if len(seg) * CHUNK_MS >= SEG_MIN_MS:
        seg_q.put((tag, np.concatenate(seg).astype("float32")))


def monitor_loop(audio_q: queue.Queue, seg_q: queue.Queue, tag: str) -> None:
    """VAD-сегментатор одного канала + детект старта/остановки сессии."""
    vad = AdaptiveVAD()
    ring = deque(maxlen=PREBUF_MS // CHUNK_MS)     # предзапись 3 с
    win = deque(maxlen=SUSTAINED_WIN)              # окно устойчивости речи
    speaking, seg, sil = False, [], 0
    speech_run = 0                                 # дебаунс открытия фразы
    speech_frames = 0                              # речевых кадров в текущей фразе
    seen_stop_gen = 0

    while not STOP.is_set():
        try:
            frame = audio_q.get(timeout=0.5)
        except queue.Empty:
            continue

        is_sp = vad.is_speech(frame)
        if is_sp:
            with STATE.lock:
                STATE.last_speech = time.time()
        win.append(1 if is_sp else 0)
        ring.append(frame)
        sustained = len(win) >= SUSTAINED_WIN - 10 and sum(win) >= SUSTAINED_MIN

        # ---- ручная остановка (атомарно, все каналы сбрасывают буферы) ----
        with STATE.lock:
            stop_now = STATE.manual_stop_gen != seen_stop_gen
            seen_stop_gen = STATE.manual_stop_gen
            was_rec = STATE.recording
        if stop_now:
            if was_rec:
                _flush(seg, seg_q, tag)
                stop_recording("manual")
            speaking, seg, sil = False, [], 0
            speech_run, speech_frames = 0, 0
            continue

        # ---- автозапуск: атомарно, сессию открывает ровно один канал ----
        if not STATE.recording and CFG.get("auto_start", True) and sustained:
            with STATE.lock:
                if not STATE.recording and time.time() >= STATE.cooldown_until:
                    conf = bool(STATE.conf_names)
                    if CFG.get("trigger") == "sound" or conf:
                        _begin_session("proc" if conf else "sound")
                        seg, speaking, sil = list(ring), True, 0
                        speech_run, speech_frames = 0, 0
                        win.clear()

        # ---- сборка фраз ----
        if STATE.recording:
            if speaking:
                seg.append(frame)
                if is_sp:
                    sil = 0
                    speech_frames += 1
                else:
                    sil += CHUNK_MS
                if sil >= SEG_SILENCE_MS or len(seg) * CHUNK_MS >= SEG_MAX_MS:
                    by_silence = sil >= SEG_SILENCE_MS
                    if speech_frames >= _MIN_SPEECH_FRAMES:
                        _flush(seg, seg_q, tag)
                    if by_silence:
                        speaking = False
                    seg, sil, speech_frames = [], 0, 0
            else:
                # открываем фразу только после устойчивой речи, а не от
                # единичного шумового кадра:
                speech_run = speech_run + 1 if is_sp else 0
                if speech_run >= _START_DEBOUNCE:
                    seg, speaking = list(ring), True
                    speech_frames = _START_DEBOUNCE
                    speech_run, sil = 0, 0

            # ---- автостоп (только авто-сессии, по активности любого канала) ----
            if STATE.trigger_kind in ("proc", "sound"):
                with STATE.lock:
                    conf = bool(STATE.conf_names)
                    idle = time.time() - STATE.last_speech > \
                        float(CFG.get("silence_timeout", 180))
                if (STATE.trigger_kind == "proc" and not conf) or idle:
                    if speech_frames >= _MIN_SPEECH_FRAMES:
                        _flush(seg, seg_q, tag)
                    speaking, seg, sil = False, [], 0
                    speech_run, speech_frames = 0, 0
                    stop_recording("silence" if idle else "proc")


def transcriber_loop(seg_q: queue.Queue) -> None:
    """Единый поток распознавания: элементы очереди — (тег канала, аудио)."""
    while True:
        try:
            tag, audio = seg_q.get(timeout=0.3)
        except queue.Empty:
            if STOP.is_set():
                return
            continue

        try:
            parts = asr.transcribe(audio)
        except Exception:
            log.exception("ошибка распознавания")
            ui("flash", "⚠ Ошибка распознавания (см. лог)")
            time.sleep(2)
            continue
        log.info("канал %s: сегмент %.1f с -> фраз: %d",
                 tag, len(audio) / 16000.0, len(parts))
        if not parts:
            continue

        prefix = TAGS.get(tag, tag)
        line = f"[{datetime.now():%H:%M:%S}] {prefix}: " + " ".join(parts)
        with STATE.lock:
            path = STATE.session_file
        if path:
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                log.error("запись в файл: %s", exc)
        ui("line", line)
        if CFG.get("auto_copy"):
            ui("clip", " ".join(parts))