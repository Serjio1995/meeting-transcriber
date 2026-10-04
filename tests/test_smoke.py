import numpy as np

from transcriber.config import CFG
from transcriber.vad import AdaptiveVAD


def test_vad_detects_speech_after_silence():
    vad = AdaptiveVAD()
    for _ in range(30):
        vad.is_speech(np.zeros(1600, dtype=np.float32))
    loud = (np.sin(np.linspace(0, 100, 1600)) * 0.3).astype(np.float32)
    assert vad.is_speech(loud)


def test_vad_ignores_silence():
    vad = AdaptiveVAD()
    for _ in range(5):
        assert not vad.is_speech(np.zeros(1600, dtype=np.float32))


def test_cfg_has_required_keys():
    for key in ("model", "compute", "language", "source", "trigger",
                "processes", "silence_timeout"):
        assert key in CFG