from pathlib import Path
import sys
import wave

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def tone_audio(tmp_path):
    rate = 48000
    time = np.arange(rate * 4) / rate
    # Distinct frequency regions give an independent reference for exact cuts.
    data = np.sin(2 * np.pi * np.where(time < 2, 440, 880) * time) * 0.35
    path = tmp_path / "test.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((data * 32767).astype("<i2").tobytes())
    return path
