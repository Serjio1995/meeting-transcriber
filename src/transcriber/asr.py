"""Фасад ASR: выбор движка, нормализация, фильтры."""

import numpy as np

from .constants import HALLUCINATIONS
from .models import get_engine


def transcribe(audio: np.ndarray) -> list[str]:
    peak = float(np.max(np.abs(audio)))
    if peak <= 0:
        return []
    if peak < 0.5:
        audio = (audio / peak * 0.7).astype("float32")
    parts = get_engine().transcribe(audio)
    return [p for p in parts
            if p.lower().strip(" .!?,…—-\"'") not in HALLUCINATIONS]