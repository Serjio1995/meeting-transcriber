"""Конфигурация и каталоги данных с учётом ОС (работает и в frozen-сборке)."""

import json
import logging
import os
import sys
import threading
from pathlib import Path

from .constants import APP_ID, DEFAULTS

log = logging.getLogger(__name__)


def data_dir() -> Path:
    """Каталог данных приложения: %APPDATA% / ~/Library/Application Support / XDG."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_PATH = data_dir() / "config.json"
TRANSCRIPT_DIR = data_dir() / "transcripts"

_lock = threading.Lock()


def save_config(cfg: dict | None = None) -> None:
    cfg = cfg if cfg is not None else CFG
    try:
        with _lock, open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        log.error("не сохранить конфиг %s: %s", CONFIG_PATH, exc)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        save_config(cfg)
    except (OSError, ValueError) as exc:
        log.warning("конфиг повреждён, использую значения по умолчанию: %s", exc)
        save_config(cfg)
    return cfg


CFG = load_config()