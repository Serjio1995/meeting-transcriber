"""Энергетический детектор речи: адаптивный шум + мягкое автоусиление (AGC)."""

import numpy as np


class AdaptiveVAD:
    """Держит медленную оценку пика сигнала и подтягивает тихий микрофон
    к рабочему диапазону, сохраняя контраст речь/тишина."""

    def __init__(self, ratio: float = 2.5, floor: float = 0.05,
                 agc_peak: float = 0.5, agc_max: float = 50.0):
        self.noise: float | None = None
        self.ratio = ratio
        self.floor = floor              # порог на УСИЛЕННОМ сигнале
        self.peak = agc_peak            # медленная оценка пика
        self.agc_peak = agc_peak
        self.agc_max = agc_max

    def is_speech(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-10)
        # медленный follower пика (постоянная времени ~3 с)
        self.peak += 0.03 * (max(rms, 1e-5) - self.peak)
        gain = min(max(self.agc_peak / self.peak, 1.0), self.agc_max)
        loud = rms * gain

        if self.noise is None:
            self.noise = max(loud, 1e-3)
        if loud < self.noise * 1.6:     # тихий кадр -> дообучаем уровень шума
            self.noise = 0.95 * self.noise + 0.05 * loud
        return loud > max(self.noise * self.ratio, self.floor)