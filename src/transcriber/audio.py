"""Захват аудио. Микрофон — sounddevice/PortAudio (надёжен на Windows),
системный звук — soundcard/WASAPI loopback. Fallback микрофона — soundcard."""

import logging
import sys
import threading

import numpy as np
import soundcard as sc

from .constants import CHUNK, SAMPLE_RATE, TAG_MIC, TAG_SYS
from .state import STATE, STOP, ui

log = logging.getLogger(__name__)

try:
    import sounddevice as _sd
    _SD_OK = True
except Exception as _exc:                       # pragma: no cover
    _SD_OK = False
    _SD_ERR = str(_exc)
    log.warning("sounddevice недоступен (%s) — микрофон через soundcard", _SD_ERR)


def list_mic_devices():
    """[(метка, индекс)] — индексы относятся к активному бэкенду."""
    if _SD_OK:
        try:
            default_in = _sd.default.device[0]
            out = []
            for i, d in enumerate(_sd.query_devices()):
                if d.get("max_input_channels", 0) > 0:
                    mark = "★ " if i == default_in else ""
                    api = _sd.query_hostapis(d["hostapi"])["name"]
                    api = (api.replace("MME", "").replace("Windows ", "")
                              .replace("DirectSound", "").strip())
                    out.append((f"{mark}{d['name'][:48]} [{api}]", i))
            if out:
                return out
        except Exception as exc:
            log.error("sounddevice: %s", exc)
    try:
        return [(f"🎙 {d.name[:55]}", i)
                for i, d in enumerate(sc.all_microphones(include_loopback=True))
                if not getattr(d, "isloopback", False)]
    except Exception:
        return []


def _sd_default_input():
    if not _SD_OK:
        return None
    try:
        return _sd.default.device[0]
    except Exception:
        return None


def _pick_sys_device():
    try:
        devs = sc.all_microphones(include_loopback=True)
    except Exception as exc:
        log.error("soundcard: %s", exc)
        return None
    loop = [d for d in devs if getattr(d, "isloopback", False)]
    if sys.platform == "darwin":
        bh = [d for d in loop if "blackhole" in d.name.lower()]
        if bh:
            STATE.blackhole_hint = False
            return bh[0]
        STATE.blackhole_hint = True
        return None
    if not loop:
        return None
    try:                                # loopback устройства по умолчанию
        spk = sc.default_speaker()
        for d in loop:
            if d.name == spk.name:
                return d
    except Exception:
        pass
    return loop[0]


def pick_devices(cfg):
    """[(backend, payload, tag)]; backend: 'sd' (PortAudio) | 'sc' (soundcard)."""
    src = cfg.get("source", "dual")
    result = []
    if src in ("loopback", "dual"):
        d = _pick_sys_device()
        if d is not None:
            result.append(("sc", d, TAG_SYS))
        elif sys.platform == "darwin":
            log.warning("macOS: BlackHole не найден — канал участников недоступен")
    if src in ("mic", "dual"):
        placed = False
        if _SD_OK:
            did = cfg.get("mic_device_id")
            if not (isinstance(did, int) and did >= 0):
                did = _sd_default_input()
            try:
                if did is not None and 0 <= did < len(_sd.query_devices()):
                    result.append(("sd", did, TAG_MIC))
                    placed = True
            except Exception:
                pass
        if not placed:
            try:
                result.append(("sc", sc.default_microphone(), TAG_MIC))
            except Exception:
                log.warning("микрофон не найден")
    if not result:
        result.append(("sc", sc.default_microphone(), TAG_MIC))
    return result


def capture_sd(dev_idx: int, audio_q, tag: str) -> None:
    """Захват микрофона через PortAudio — восстанавливается после ошибок."""
    try:
        name = _sd.query_devices(dev_idx)["name"]
    except Exception:
        name = f"device #{dev_idx}"
    while not STOP.is_set():
        try:
            with _sd.InputStream(device=dev_idx, samplerate=SAMPLE_RATE,
                                 channels=1, dtype="float32",
                                 blocksize=CHUNK) as stream:
                log.info("захват микрофона [PortAudio]: %s", name)
                STATE.audio_ok = True
                while not STOP.is_set():
                    data, overflow = stream.read(CHUNK)
                    if overflow:
                        log.warning("переполнение буфера микрофона")
                    mono = np.ascontiguousarray(data[:, 0], dtype="float32")
                    with STATE.lock:
                        STATE.levels[tag] = float(np.sqrt(np.mean(mono ** 2)))
                    audio_q.put(mono)
        except Exception as exc:
            STATE.audio_ok = False
            log.error("микрофон [PortAudio]: %s — повтор через 3 с", exc)
            ui("flash", f"⚠ Микрофон: {exc} — повтор…")
            STOP.wait(3)


def capture_sc(device, audio_q, tag: str) -> None:
    """Захват через soundcard (loopback или fallback-микрофон)."""
    while not STOP.is_set():
        try:
            with device.recorder(samplerate=SAMPLE_RATE, blocksize=CHUNK) as rec:
                log.info("захват аудио [%s]: %s", tag, device.name)
                STATE.audio_ok = True
                while not STOP.is_set():
                    data = rec.record(numframes=CHUNK)
                    mono = data.mean(axis=1).astype("float32")
                    with STATE.lock:
                        STATE.levels[tag] = float(np.sqrt(np.mean(mono ** 2)))
                    audio_q.put(mono)
        except Exception as exc:
            STATE.audio_ok = False
            log.error("ошибка захвата [%s]: %s — повтор через 3 с", tag, exc)
            ui("flash", f"⚠ Ошибка аудио: {exc} — повтор…")
            STOP.wait(3)


def probe_level(dev_idx, callback):
    """Живой уровень микрофона для мастера. Возвращает функцию stop()."""
    stop_flag = threading.Event()

    def _push(rms):
        callback(max(0.0, min(1.0, rms * 6.0)))

    if _SD_OK:
        idx = _sd_default_input() if dev_idx is None else dev_idx

        def run_sd():
            try:
                with _sd.InputStream(device=idx, samplerate=SAMPLE_RATE,
                                     channels=1, dtype="float32",
                                     blocksize=CHUNK) as st:
                    while not stop_flag.is_set():
                        data, _ = st.read(CHUNK)
                        _push(float(np.sqrt(np.mean(data[:, 0] ** 2))))
            except Exception as exc:
                log.error("probe: %s", exc)
                callback(-1.0)

        threading.Thread(target=run_sd, daemon=True).start()
        return stop_flag.set

    def run_sc():
        try:
            dev = sc.default_microphone()
            with dev.recorder(samplerate=SAMPLE_RATE, blocksize=CHUNK) as rec:
                while not stop_flag.is_set():
                    d = rec.record(numframes=CHUNK)
                    _push(float(np.sqrt(np.mean(d.mean(axis=1) ** 2))))
        except Exception as exc:
            log.error("probe: %s", exc)
            callback(-1.0)

    threading.Thread(target=run_sc, daemon=True).start()
    return stop_flag.set