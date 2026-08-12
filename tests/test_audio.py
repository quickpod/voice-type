"""Audio helper tests: WAV reading, downmix and resample (soundfile+numpy)."""

import numpy as np
import soundfile as sf

from voicetype import audio


def _sine(freq, seconds, rate):
    t = np.linspace(0, seconds, int(seconds * rate), endpoint=False)
    return 0.25 * np.sin(2 * np.pi * freq * t)


def test_read_16k_mono_wav(tmp_path):
    rate = 16000
    data = _sine(220, 0.5, rate).astype("float32")
    p = tmp_path / "mono16k.wav"
    sf.write(str(p), data, rate)

    pcm, out_rate = audio.read_wav_16k_mono(str(p))
    assert out_rate == 16000
    assert pcm.dtype == np.dtype("<i2")
    assert abs(len(pcm) - 8000) <= 2  # 0.5s * 16k


def test_read_resamples_8k_to_16k(tmp_path):
    src_rate = 8000
    data = _sine(200, 1.0, src_rate).astype("float32")
    p = tmp_path / "mono8k.wav"
    sf.write(str(p), data, src_rate)

    pcm, out_rate = audio.read_wav_16k_mono(str(p))
    assert out_rate == 16000
    # ~1 second at 16k
    assert abs(len(pcm) - 16000) <= 4


def test_stereo_is_downmixed(tmp_path):
    rate = 16000
    left = _sine(200, 0.25, rate)
    right = _sine(400, 0.25, rate)
    stereo = np.stack([left, right], axis=1).astype("float32")
    p = tmp_path / "stereo.wav"
    sf.write(str(p), stereo, rate)

    pcm, out_rate = audio.read_wav_16k_mono(str(p))
    assert out_rate == 16000
    assert pcm.ndim == 1
    assert abs(len(pcm) - 4000) <= 2


def test_read_wav_info(tmp_path):
    rate = 16000
    data = _sine(300, 2.0, rate).astype("float32")
    p = tmp_path / "info.wav"
    sf.write(str(p), data, rate)
    info = audio.read_wav_info(str(p))
    assert info["samplerate"] == 16000
    assert info["channels"] == 1
    assert abs(info["seconds"] - 2.0) < 0.01


def test_resample_length_and_identity():
    src = np.arange(1000, dtype=float)
    up = audio.resample(src, 8000, 16000)
    assert abs(len(up) - 2000) <= 2
    same = audio.resample(src, 16000, 16000)
    assert len(same) == 1000


def test_float_to_int16_clips():
    out = audio.float_to_int16(np.array([0.0, 1.0, -1.0, 2.0, -2.0]))
    assert out.dtype == np.dtype("<i2")
    assert out[0] == 0
    assert out[1] == 32767
    assert out[2] == -32767
    assert out[3] == 32767  # clipped
    assert out[4] == -32767
