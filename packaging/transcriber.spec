# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: onedir-сборка для Windows (мгновенный старт) или onefile
(ONEFILE=1); .app-бандл для macOS.

Запуск из корня репозитория:
    python -m PyInstaller packaging/transcriber.spec --noconfirm --clean

Переменные окружения:
    ONEFILE=1   — собрать один exe вместо папки
    WITH_CUDA=1 — упаковать pip-пакеты nvidia-* (сборка ~2 ГБ)
"""
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = "MeetingTranscriber"
VERSION = "1.1.0"

datas, binaries, hiddenimports = [], [], [
    # бэкенды, импортируемые библиотеками динамически:
    "soundcard.mediafoundation", "soundcard.coreaudio", "soundcard.pulseaudio",
    "pystray._win32", "pystray._darwin", "pystray._xorg",
    "keyboard",
]

# Пакеты, которые нужно тащить в сборку целиком (данные + бинарники + скрытые
# импорты): sounddevice — PortAudio-микрофон, vosk — второй движок ASR,
# requests(+сертификаты) — загрузчик моделей.
for pkg in ("faster_whisper", "ctranslate2", "tokenizers", "av", "onnxruntime",
            "huggingface_hub", "numpy",
            "soundcard", "sounddevice", "vosk",
            "requests", "charset_normalizer", "certifi", "urllib3", "idna",
            "pystray", "psutil", "pyperclip"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

icon_png = os.path.join(ROOT, "assets", "icon.png")
if os.path.exists(icon_png):
    datas.append((icon_png, "assets"))

if os.environ.get("WITH_CUDA") == "1":
    for n in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime",
              "nvidia.nvjitlink", "nvidia.cufft"):
        if importlib.util.find_spec(n):
            d, b, h = collect_all(n)
            datas += d
            binaries += b
            hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "run.py")],          # лаунчер: фикс относительных импортов
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=("torch", "matplotlib", "pandas", "scipy", "PyQt5", "PyQt6",
              "PySide2", "PySide6", "IPython", "pytest"),
    noarchive=False,
)
pyz = PYZ(a.pure)

ico = os.path.join(ROOT, "assets", "icon.ico")
icns = os.path.join(ROOT, "assets", "icon.icns")
ver = os.path.join(ROOT, "packaging", "version_info.txt")

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP,
              console=False, icon=icns if os.path.exists(icns) else None)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP)
    app = BUNDLE(
        coll,
        name="Meeting Transcriber.app",
        icon=icns if os.path.exists(icns) else None,
        info_plist={
            "CFBundleDisplayName": "Meeting Transcriber",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "CFBundleIdentifier": "ru.meetingtranscriber.app",
            "NSMicrophoneUsageDescription":
                "Приложению нужен доступ к микрофону или BlackHole "
                "для транскрибации звука конференций.",
            "LSMinimumSystemVersion": "11.0",
        },
    )
else:
    if os.environ.get("ONEFILE", "0") == "1":
        exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
                  name=APP, console=False, upx=False,
                  icon=ico if os.path.exists(ico) else None,
                  version=ver if os.path.exists(ver) else None)
    else:
        # onedir: без распаковки в %TEMP% при каждом запуске — старт мгновенный
        exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP,
                  console=False, upx=False,
                  icon=ico if os.path.exists(ico) else None,
                  version=ver if os.path.exists(ver) else None)
        COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP)