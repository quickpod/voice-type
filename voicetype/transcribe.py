r"""Offline transcription built on Vosk's ``KaldiRecognizer``.

``import vosk`` happens **lazily**, inside :func:`_load_model`, so this module
imports on a box without the native library or any speech model.  A missing
library or model is reported as a :class:`VoiceTypeError` with guidance.

The public result shape is deliberately small and JSON-friendly::

    TranscriptResult.text        -> str, the full transcript
    TranscriptResult.segments    -> [ {start, end, text, words?}, ... ]

where ``words`` (present when ``words=True``) is a list of
``{word, start, end, conf}`` dicts.  Segment start/end are seconds (floats) and
are populated from word timings whenever Vosk provides them, so
:func:`to_srt` / :func:`to_vtt` produce correctly-timed subtitles.
"""

from __future__ import annotations

import json

from . import audio
from .errors import VoiceTypeError


class TranscriptResult:
    """A transcript: the joined ``text`` plus timed ``segments``."""

    __slots__ = ("text", "segments")

    def __init__(self, text, segments):
        self.text = text
        self.segments = segments

    def to_dict(self):
        return {"text": self.text, "segments": [dict(s) for s in self.segments]}

    def __repr__(self):
        return f"TranscriptResult(text={self.text!r}, segments={len(self.segments)})"


# ---------------------------------------------------------------------------
# Lazy Vosk loading
# ---------------------------------------------------------------------------
def _import_vosk():
    try:
        import vosk  # noqa: PLC0415 - intentional lazy import
    except Exception as exc:  # noqa: BLE001 - ImportError / native load failure
        raise VoiceTypeError(
            "the Vosk speech engine is not available (import failed: "
            f"{exc}). Install it with 'pip install vosk'. VoiceType uses Vosk "
            "for 100% offline recognition."
        ) from exc
    return vosk


def _load_model(model_dir):
    import os

    if not model_dir or not os.path.isdir(model_dir):
        raise VoiceTypeError(
            f"speech model directory not found: {model_dir!r}. Install one with "
            "'voicetype models install vosk-model-small-en-us-0.15'."
        )
    vosk = _import_vosk()
    try:
        vosk.SetLogLevel(-1)  # keep the console quiet
    except Exception:
        pass
    try:
        return vosk.Model(model_dir)
    except Exception as exc:  # noqa: BLE001
        raise VoiceTypeError(
            f"could not load speech model at {model_dir!r}: {exc}"
        ) from exc


def _make_recognizer(model_dir, *, words):
    vosk = _import_vosk()
    model = _load_model(model_dir)
    rec = vosk.KaldiRecognizer(model, audio.TARGET_RATE)
    # Always request word timings so segments carry start/end for subtitles.
    try:
        rec.SetWords(True)
    except Exception:
        pass
    return rec


def _segment_from_result(obj, *, words):
    """Build a segment dict from a Vosk result JSON object."""
    text = (obj.get("text") or "").strip()
    word_list = obj.get("result") or []
    start = end = None
    if word_list:
        start = float(word_list[0].get("start", 0.0))
        end = float(word_list[-1].get("end", start))
    seg = {"start": start, "end": end, "text": text}
    if words:
        seg["words"] = [
            {
                "word": w.get("word", ""),
                "start": float(w.get("start", 0.0)),
                "end": float(w.get("end", 0.0)),
                "conf": float(w.get("conf", 1.0)),
            }
            for w in word_list
        ]
    return seg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def transcribe_stream(wav_path, model_dir, *, words=False, chunk_frames=4000):
    """Yield finalized segment dicts as *wav_path* is decoded (streaming).

    Each yielded item has the same shape as an entry in
    :attr:`TranscriptResult.segments`.  Empty segments (silence) are skipped.
    """
    pcm, _rate = audio.read_wav_16k_mono(wav_path)
    rec = _make_recognizer(model_dir, words=words)

    data = pcm.tobytes()
    step = max(1, chunk_frames) * 2  # int16 -> 2 bytes per frame
    for i in range(0, len(data), step):
        chunk = data[i:i + step]
        if rec.AcceptWaveform(chunk):
            seg = _segment_from_result(json.loads(rec.Result()), words=words)
            if seg["text"]:
                yield seg
    final = _segment_from_result(json.loads(rec.FinalResult()), words=words)
    if final["text"]:
        yield final


def transcribe_file(wav_path, model_dir, *, words=False):
    """Transcribe *wav_path* using the Vosk model at *model_dir*.

    Returns a :class:`TranscriptResult`.  The audio is decoded, downmixed to
    mono and resampled to 16 kHz automatically.
    """
    segments = list(transcribe_stream(wav_path, model_dir, words=words))
    text = " ".join(s["text"] for s in segments if s["text"]).strip()
    return TranscriptResult(text, segments)


# ---------------------------------------------------------------------------
# Exporters (pure functions -- no native deps, fully unit-testable)
# ---------------------------------------------------------------------------
def _as_segments(result_or_segments):
    if isinstance(result_or_segments, TranscriptResult):
        return result_or_segments.segments
    return result_or_segments


def to_txt(result_or_segments):
    """Return plain text: one line per non-empty segment."""
    segs = _as_segments(result_or_segments)
    lines = [(s.get("text") or "").strip() for s in segs]
    return "\n".join(line for line in lines if line)


def _fmt_ts(seconds, sep=","):
    """Format *seconds* as ``HH:MM:SS,mmm`` (SRT) or ``HH:MM:SS.mmm`` (VTT)."""
    if seconds is None or seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(result_or_segments):
    """Render timed segments to an SRT subtitle string."""
    segs = _as_segments(result_or_segments)
    blocks = []
    index = 1
    prev_end = 0.0
    for seg in segs:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start")
        end = seg.get("end")
        if start is None:
            start = prev_end
        if end is None or end <= start:
            end = start + 2.0  # fallback duration when timings are absent
        blocks.append(
            f"{index}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{text}\n"
        )
        prev_end = end
        index += 1
    return "\n".join(blocks)


def to_vtt(result_or_segments):
    """Render timed segments to a WebVTT subtitle string."""
    segs = _as_segments(result_or_segments)
    out = ["WEBVTT", ""]
    prev_end = 0.0
    for seg in segs:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start")
        end = seg.get("end")
        if start is None:
            start = prev_end
        if end is None or end <= start:
            end = start + 2.0
        out.append(f"{_fmt_ts(start, '.')} --> {_fmt_ts(end, '.')}")
        out.append(text)
        out.append("")
        prev_end = end
    return "\n".join(out)


__all__ = [
    "TranscriptResult",
    "transcribe_file",
    "transcribe_stream",
    "to_txt",
    "to_srt",
    "to_vtt",
]
