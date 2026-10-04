"""Лаунчер для сборки PyInstaller.

Нельзя указывать точкой входа src/transcriber/__main__.py напрямую:
PyInstaller исполняет его как верхнеуровневый скрипт, и относительные
импорты (from . import ...) падают. Этот файл импортирует пакет
абсолютным именем и запускает приложение.
"""
import multiprocessing
import sys

from transcriber.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())