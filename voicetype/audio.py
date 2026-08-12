r"""Audio helpers for VoiceType.

Reading/decoding WAV data uses ``soundfile`` + ``numpy`` (both permissive and
imported at module top -- they are pure-ish wheels, not the heavy native STT
stack).  Anything that touches a live microphone (``sounddevice``) is imported
*lazily* inside functions so this module -- and the whole package -- imports
cleanly on a headless box with no audio backend.

Vosk's ``KaldiRecognizer`` wants **16 kHz, mono, 16-bit PCM**.  The helpers here
normalise arbitrary WAV input to that shape.
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from .errors import VoiceTypeError

TARGET_RATE = 16000


def to_mono(data):
    """Collapse a (frames, channels) array to mono (frames,) by averaging."""
    arr = np.asarray(data)
    if arr.ndim == 2:
        if arr.shape[1] == 1:
            return arr[:, 0]
        return arr.mean(axis=1)
    return arr


def resample(data, src_rate, dst_rate=TARGET_RATE):
    """Resample mono float samples from *src_rate* to *dst_rate*.

    Uses straightforward linear interpolation -- adequate for speech recognition
    and dependency-free.  Returns ``float`` samples.
    """
    arr = np.asarray(data, dtype=np.float64)
    if src_rate == dst_rate or arr.size == 0:
        return arr
    if src_rate <= 0:
        raise VoiceTypeError(f"invalid sample rate: {src_rate}")
    duration = arr.shape[0] / float(src_rate)
    n_out = int(round(duration * dst_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float64)
    # Sample positions of the source and (evenly spaced) destination frames.
    src_idx = np.arange(arr.shape[0], dtype=np.float64)
    dst_idx = np.linspace(0, arr.shape[0] - 1, n_out)
    return np.interp(dst_idx, src_idx, arr)


def float_to_int16(data):
    """Convert float samples in [-1, 1] to little-endian int16 PCM."""
    arr = np.asarray(data, dtype=np.float64)
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype("<i2")


def read_wav_16k_mono(path):
    """Read *path* and return (int16_pcm ndarray, 16000).

    The audio is decoded, downmixed to mono and resampled to 16 kHz.  The
    returned array is 16-bit PCM ready to feed to a Vosk recognizer via
    ``.tobytes()``.  Raises :class:`VoiceTypeError` if the file cannot be read.
    """
    data, rate = _read(path)
    mono = to_mono(data)
    mono = resample(mono, rate, TARGET_RATE)
    return float_to_int16(mono), TARGET_RATE


def read_wav_info(path):
    """Return metadata for *path* as a dict: samplerate, channels, frames, seconds."""
    try:
        info = sf.info(path)
    except Exception as exc:  # noqa: BLE001
        raise VoiceTypeError(f"could not read audio file {path!r}: {exc}") from exc
    return {
        "samplerate": info.samplerate,
        "channels": info.channels,
        "frames": info.frames,
        "seconds": (info.frames / info.samplerate) if info.samplerate else 0.0,
        "format": info.format,
    }


def _read(path):
    """Decode *path* to (float64 samples, samplerate)."""
    try:
        data, rate = sf.read(path, dtype="float32", always_2d=False)
    except Exception as exc:  # noqa: BLE001 - normalise to our error type
        raise VoiceTypeError(
            f"could not read audio file {path!r}: {exc}. "
            "Provide a WAV/FLAC/OGG file (16 kHz mono works best)."
        ) from exc
    return np.asarray(data, dtype=np.float64), rate


def write_wav(path, data, rate=TARGET_RATE):
    """Write mono float/int16 *data* to a WAV file (used mainly by tests)."""
    try:
        sf.write(path, np.asarray(data), rate)
    except Exception as exc:  # noqa: BLE001
        raise VoiceTypeError(f"could not write audio file {path!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# Live input devices (lazy sounddevice)
# ---------------------------------------------------------------------------
def list_input_devices():
    """Return input devices as ``[{'index', 'name', 'channels', 'default'}]``.

    ``sounddevice`` is imported lazily; if it (or PortAudio) is unavailable we
    raise :class:`VoiceTypeError` with guidance rather than crashing at import.
    """
    sd = _import_sounddevice()
    try:
        devices = sd.query_devices()
        default_in = None
        try:
            default_in = sd.default.device[0]
        except Exception:
            default_in = None
        out = []
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                out.append({
                    "index": idx,
                    "name": dev.get("name", f"device {idx}"),
                    "channels": dev.get("max_input_channels", 0),
                    "default": idx == default_in,
                })
        return out
    except Exception as exc:  # noqa: BLE001
        raise VoiceTypeError(f"could not query audio input devices: {exc}") from exc


def _import_sounddevice():
    """Import ``sounddevice`` lazily, translating failures to VoiceTypeError."""
    try:
        import sounddevice  # noqa: PLC0415 - intentional lazy import
    except Exception as exc:  # noqa: BLE001 - includes OSError for missing PortAudio
        raise VoiceTypeError(
            "microphone support needs the 'sounddevice' package (and PortAudio) "
            "which is not available here. Install it with 'pip install "
            "sounddevice'. File transcription does not require it."
        ) from exc
    return sounddevice


__all__ = [
    "TARGET_RATE",
    "to_mono",
    "resample",
    "float_to_int16",
    "read_wav_16k_mono",
    "read_wav_info",
    "write_wav",
    "list_input_devices",
]
