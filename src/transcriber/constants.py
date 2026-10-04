"""Константы приложения."""

APP_NAME = "Meeting Transcriber"
APP_ID = "meeting-transcriber"
VERSION = "1.1.0"

# Аудио
SAMPLE_RATE = 16000
CHUNK_MS = 100
CHUNK = SAMPLE_RATE * CHUNK_MS // 1000

# Порог устойчивой речи для автостарта: >=7 голосных кадров из 30 (3 с)
SUSTAINED_MIN = 7
SUSTAINED_WIN = 30
PREBUF_MS = 3000                 # предзапись до триггера

# Пауза внутри фразы и предел длины фразы
SEG_SILENCE_MS = 800
SEG_MAX_MS = 20000
SEG_MIN_MS = 400

# Порт для защиты от второго экземпляра
LOCK_PORT = 57321

STATUS_COLORS = {"idle": "#607d8b", "wait": "#ff9800",
                 "rec": "#e53935", "load": "#3f51b5"}

TAG_SYS = "sys"                  # системный звук: участники, видео, демонстрация
TAG_MIC = "mic"                  # микрофон пользователя

DEFAULTS = {
    "setup_done": False,           # мастер первичной настройки пройден
    "quality": "balanced",         # fast | balanced | best (пресет из мастера)
    "engine": "auto",              # auto (по пресету) | whisper | vosk
    "model": "auto",               # whisper: tiny/base/small/medium/large-v3-turbo
    "compute": "auto",             # auto/cpu/cuda
    "language": "ru",
    "source": "dual",              # dual | loopback | mic
    "device_id": None,             # сист. звук (индекс soundcard)
    "mic_device_id": None,         # микрофон (индекс sounddevice/PortAudio)
    "beam": 5,
    "prompt": "",
    "trigger": "process+sound",    # process+sound | sound
    "include_browsers": False,
    "auto_start": True,
    "auto_copy": False,
    "silence_timeout": 180,        # сек тишины до автоостановки
    "hotkeys": True,
    "hf_endpoint": "",             # своё зеркало HF (пусто = авто-перебор)
    "processes": ["zoom", "teams", "ms-teams", "msteams", "webex", "trueconf",
                  "skype", "discord", "viber", "slack", "vkteams", "sferum"],
    "browsers": ["chrome", "msedge", "firefox", "browser", "yandex",
                 "opera", "brave", "vivaldi"],
}

# Типовые «галлюцинации» Whisper на тишине/шуме
HALLUCINATIONS = {
    "спасибо за просмотр", "подпишитесь на канал", "продолжение следует",
    "до новых встреч", "thanks for watching", "bye bye", "amara.org",
    "subtitles by", "продолжение в следующем видео",
}