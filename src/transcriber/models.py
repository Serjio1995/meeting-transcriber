"""Менеджер моделей и движков ASR: Whisper (faster-whisper) и Vosk.

Загрузка:
- сначала hf-mirror.com, затем huggingface.co (перебор автоматом);
- файлы >8 МБ качаются параллельно (8 соединений) с докачкой частей;
- HTTP 404 не ретраится: опциональные файлы пропускаются;
- кэш в data_dir()/models: повторные запуски ничего не качают.
"""

import json
import logging
import os
import shutil
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests

from .config import CFG, data_dir
from .constants import SAMPLE_RATE
from .state import STATE, ui

log = logging.getLogger(__name__)

MODELS_DIR = data_dir() / "models"
HF_BASES = ["https://hf-mirror.com", "https://huggingface.co"]
VOSK_URL = "https://alphacephei.com/vosk/models/{}.zip"
WHISPER_REPO = "Systran/faster-whisper-{}"

# Обязательные файлы у всех Systran/faster-whisper-*
WHISPER_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
# Есть не у всех моделей (у small отсутствует) — при 404 просто пропускаем:
WHISPER_OPTIONAL = ["preprocessor_config.json"]

VOSK_SMALL = {"ru": "vosk-model-small-ru-0.22",
              "en": "vosk-model-small-en-us-0.15"}

QUALITY = {
    "fast": "⚡ Быстрый — Vosk small (~45 МБ, мгновенный отклик, ниже точность)",
    "balanced": "⚖ Сбалансированный — Whisper small (~460 МБ)",
    "best": "🎯 Максимальная точность — Whisper large-v3-turbo (~1.5 ГБ)",
}

UA = {"User-Agent": "meeting-transcriber/1.1"}
PARALLEL_MIN = 8 << 20          # файлы больше 8 МБ качаем параллельно
PARTS = 8
ATTEMPTS = 5
TIMEOUT = (10, 60)              # (connect, read): 60 с между кусками — с запасом
EMIT_EVERY = 0.4

_engine = None
_sig = None
_lock = threading.Lock()
_emit_lock = threading.Lock()
_last_emit = [0.0]


class _NotFound(Exception):
    """Файла нет на сервере (HTTP 404/410) — ретраить бессмысленно."""


# ------------------------------- загрузчик -----------------------------------
def _emit(name, pct=None, done=False, error=None):
    d = {"name": name, "pct": pct, "done": done, "error": error}
    with STATE.lock:
        STATE.last_download = d
    ui("download", d)


def _emit_progress(label: str, pct: float) -> None:
    now = time.time()
    with _emit_lock:
        if now - _last_emit[0] < EMIT_EVERY and pct < 100:
            return
        _last_emit[0] = now
    _emit(label, round(pct, 1))


def _check(r) -> None:
    if r.status_code in (404, 410):
        raise _NotFound(f"HTTP {r.status_code}")
    r.raise_for_status()


def _probe(url: str) -> tuple[int, bool]:
    """(размер, поддерживается ли Range). Быстрый HEAD, чтобы не висеть."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=(8, 15), headers=UA)
        total = int(r.headers.get("Content-Length") or 0)
        ranges = "bytes" in (r.headers.get("Accept-Ranges") or "").lower()
        return total, ranges
    except Exception:
        return 0, False


def _download_stream(url: str, tmp: Path, label: str, total: int = 0) -> None:
    """Однопоточная загрузка с докачкой (мелкие файлы и fallback)."""
    done = tmp.stat().st_size if tmp.exists() else 0
    headers = dict(UA)
    if done:
        headers["Range"] = f"bytes={done}-"
    with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
        _check(r)
        resume = done > 0 and r.status_code == 206
        if not resume:
            done = 0
        with open(tmp, "ab" if resume else "wb") as fh:
            got = done
            for chunk in r.iter_content(chunk_size=1 << 18):
                if not chunk:
                    continue
                fh.write(chunk)
                got += len(chunk)
                if total:
                    _emit_progress(label, min(99.9, got / total * 100))


def _download_parts(url: str, tmp: Path, total: int, label: str) -> None:
    """Параллельная загрузка диапазонов + докачка уже скачанных частей."""
    step = total // PARTS
    bounds, start = [], 0
    for i in range(PARTS):
        end = total - 1 if i == PARTS - 1 else start + step - 1
        bounds.append((start, end))
        start = end + 1
    parts = [tmp.with_suffix(tmp.suffix + f".p{i}") for i in range(PARTS)]
    done = [0] * PARTS

    def fetch(i: int) -> None:
        s, e = bounds[i]
        want = e - s + 1
        p = parts[i]
        have = p.stat().st_size if p.exists() else 0
        if have >= want:
            done[i] = want
            return
        headers = dict(UA)
        headers["Range"] = f"bytes={s + have}-{e}" if have else f"bytes={s}-{e}"
        with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as r:
            _check(r)
            if r.status_code != 206:
                raise RuntimeError(f"нет поддержки Range (HTTP {r.status_code})")
            with open(p, "ab" if have else "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 18):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done[i] += len(chunk)
                    _emit_progress(label, min(99.9, sum(done) / total * 100))

    with ThreadPoolExecutor(max_workers=PARTS) as ex:
        futures = [ex.submit(fetch, i) for i in range(PARTS)]
        for f in as_completed(futures):
            f.result()

    for i, p in enumerate(parts):
        if p.stat().st_size != bounds[i][1] - bounds[i][0] + 1:
            raise RuntimeError(f"часть {i}: размер не сошёлся")

    with open(tmp, "wb") as out:
        for p in parts:
            with open(p, "rb") as fh:
                shutil.copyfileobj(fh, out, 1 << 20)


def _cleanup_parts(tmp: Path) -> None:
    for i in range(PARTS):
        tmp.with_suffix(tmp.suffix + f".p{i}").unlink(missing_ok=True)


def _download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(ATTEMPTS):
        try:
            total, ranges = _probe(url)
            if total and ranges and total >= PARALLEL_MIN:
                try:
                    _download_parts(url, tmp, total, label)
                except _NotFound:
                    raise
                except Exception as exc:
                    log.warning("параллельная загрузка не удалась (%s) — обычная", exc)
                    _download_stream(url, tmp, label, total)
            else:
                _download_stream(url, tmp, label, total)
            _emit_progress(label, 100.0)
            tmp.replace(dest)
            _cleanup_parts(tmp)
            return
        except _NotFound:
            raise
        except Exception as exc:
            last = exc
            log.warning("скачивание %s: %s (попытка %d/%d)",
                        url, exc, attempt + 1, ATTEMPTS)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"не удалось скачать {url}: {last}")


def _ensure_whisper(name: str) -> Path:
    d = MODELS_DIR / f"whisper-{name}"
    if all((d / f).exists() and (d / f).stat().st_size > 0
           for f in WHISPER_FILES):
        return d
    d.mkdir(parents=True, exist_ok=True)
    label = f"Whisper {name}"
    bases = ([CFG["hf_endpoint"]] if CFG.get("hf_endpoint") else []) + HF_BASES

    def _url(base, f):
        return f"{base}/{WHISPER_REPO.format(name)}/resolve/main/{f}"

    for f in WHISPER_FILES:                         # обязательные
        target = d / f
        if target.exists() and target.stat().st_size > 0:
            continue
        last: Exception | None = None
        for base in bases:
            try:
                _download(_url(base, f), target, label)
                last = None
                break
            except _NotFound as exc:
                last = exc
            except Exception as exc:
                last = exc
        if last:
            if isinstance(last, _NotFound):
                raise RuntimeError(
                    f"файл {f} отсутствует в репозитории "
                    f"{WHISPER_REPO.format(name)}. Сообщите разработчику.")
            raise RuntimeError(
                f"{last}\n\nПлан Б: скачайте файлы {WHISPER_FILES} браузером "
                f"с hf-mirror.com/Systran/faster-whisper-{name} и положите в\n{d}")
    for f in WHISPER_OPTIONAL:                      # опциональные: 404 — ок
        target = d / f
        if target.exists() and target.stat().st_size > 0:
            continue
        for base in bases:
            try:
                _download(_url(base, f), target, label)
                break
            except _NotFound:
                log.info("%s отсутствует в %s — пропускаю (не обязателен)",
                         f, WHISPER_REPO.format(name))
                break
            except Exception as exc:
                log.warning("опциональный %s: %s", f, exc)
    return d


def _ensure_vosk(mid: str) -> Path:
    d = MODELS_DIR / mid
    if (d / "conf").exists() and (d / "am").exists():
        return d
    zip_path = MODELS_DIR / f"{mid}.zip"
    if not zip_path.exists() or zip_path.stat().st_size == 0:
        url = VOSK_URL.format(mid)
        try:
            _download(url, zip_path, f"Vosk {mid}")
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc}\n\nПлан Б: скачайте архив браузером {url} и положите его "
                f"(не переименовывая) в {zip_path}, затем «Повторить».")
    _emit(f"Vosk {mid}", None)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(MODELS_DIR)
    _emit(f"Vosk {mid}", 100.0, done=True)
    if not (d / "conf").exists():
        raise RuntimeError("неожиданная структура архива Vosk")
    return d


# --------------------------------- движки ------------------------------------
def _add_cuda_dirs() -> None:
    if sys.platform != "win32":
        return
    import glob
    for base in {getattr(sys, "_MEIPASS", None), sys.prefix, *sys.path}:
        if not base:
            continue
        for dd in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(dd)
            except OSError:
                pass


class WhisperEngine:
    name = "whisper"

    def __init__(self, path: Path, model_id: str):
        _add_cuda_dirs()
        from faster_whisper import WhisperModel
        import ctranslate2
        compute = CFG.get("compute", "auto")
        if compute == "auto":
            compute = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
        ctype = "int8_float16" if compute == "cuda" else "int8"
        log.info("Whisper %s | %s | %s", model_id, compute, ctype)
        self.model = WhisperModel(
            str(path), device=compute, compute_type=ctype,
            cpu_threads=max(4, os.cpu_count() or 4),
            num_workers=1)

    def transcribe(self, audio: np.ndarray) -> list[str]:
        lang = CFG.get("language", "ru")
        segments, _ = self.model.transcribe(
            audio,
            language=None if lang == "auto" else lang,
            beam_size=int(CFG.get("beam", 5)),
            vad_filter=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            initial_prompt=(CFG.get("prompt") or None),
        )
        out = []
        for s in segments:
            t = s.text.strip()
            if t and not (s.no_speech_prob > 0.8 and s.avg_logprob < -1.0):
                out.append(t)
        return out


class VoskEngine:
    name = "vosk"

    def __init__(self, path: Path):
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        log.info("Vosk: %s", path.name)
        self.model = Model(str(path))

    def transcribe(self, audio: np.ndarray) -> list[str]:
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(self.model, SAMPLE_RATE)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("int16").tobytes()
        out = []
        step = SAMPLE_RATE * 2 * 2
        for i in range(0, len(pcm), step):
            if rec.AcceptWaveform(pcm[i:i + step]):
                t = self._text(rec.Result())
                if t:
                    out.append(t)
        t = self._text(rec.FinalResult())
        if t:
            out.append(t)
        return out

    @staticmethod
    def _text(js: str) -> str:
        try:
            return json.loads(js).get("text", "").strip()
        except Exception:
            return ""


# ------------------------------ менеджер -------------------------------------
def resolve() -> tuple[str, str]:
    """(движок, модель) с учётом пресета качества и ручных переопределений."""
    manual = CFG.get("model", "auto")
    if manual and manual != "auto":
        return "whisper", manual

    lang = CFG.get("language", "ru")
    eng = CFG.get("engine", "auto")
    q = CFG.get("quality", "balanced")
    whisper_by_quality = {"fast": "base", "balanced": "small",
                          "best": "large-v3-turbo"}

    if eng == "vosk":
        if lang in VOSK_SMALL:
            return "vosk", VOSK_SMALL[lang]
        log.warning("Vosk-модели для языка «%s» нет — Whisper", lang)
        return "whisper", whisper_by_quality.get(q, "small")
    if eng == "whisper":
        return "whisper", whisper_by_quality.get(q, "small")

    if q == "fast":
        if lang in VOSK_SMALL:
            return "vosk", VOSK_SMALL[lang]
        return "whisper", "small"
    if q == "best":
        return "whisper", "large-v3-turbo"
    return "whisper", "small"


def get_engine():
    global _engine, _sig
    with _lock:
        sig = resolve()
        if _engine is not None and _sig == sig:
            return _engine
        engine_name, model_id = sig
        try:
            if engine_name == "vosk":
                _engine = VoskEngine(_ensure_vosk(model_id))
            else:
                _engine = WhisperEngine(_ensure_whisper(model_id), model_id)
            _sig = sig
            _emit(model_id, 100.0, done=True)
        except Exception as exc:
            log.exception("не построить движок")
            _emit(model_id, error=str(exc))
            raise
        return _engine


def reset_engine() -> None:
    global _engine, _sig
    with _lock:
        _engine, _sig = None, None


def warmup() -> None:
    try:
        get_engine()
        ui("flash", "✅ Модель готова к работе")
    except Exception as exc:
        ui("flash", f"⚠ Модель не загружена: {exc}")
