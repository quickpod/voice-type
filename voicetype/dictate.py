r"""Live microphone dictation and (Windows) keystroke injection.

Everything that touches hardware or the OS input stack is imported **lazily**:

* the audio backend (``sounddevice``) is imported only when :func:`dictate`
  actually starts capturing, via :mod:`voicetype.audio`; and
* keystroke injection (:func:`type_out`) uses ``ctypes`` + the Win32 API on
  Windows and is a no-op that simply returns the text elsewhere.

So importing this module never requires a microphone, PortAudio, Vosk or a
model -- the package stays import-safe on a headless CI box.
"""

from __future__ import annotations

import json
import queue

from . import audio, transcribe
from .errors import VoiceTypeError


def dictate(model_dir, *, device=None, samplerate=None, blocksize=8000,
            stop_event=None):
    """Capture the microphone and yield recognition events until stopped.

    Yields dicts ``{"type": "partial"|"final", "text": str}``.  Partial events
    stream the in-progress phrase; a ``final`` event fires when Vosk commits an
    utterance.  Pass a :class:`threading.Event` as *stop_event* to stop cleanly
    (e.g. from a GUI "Stop" button); otherwise it runs until interrupted.

    Raises :class:`VoiceTypeError` if the audio backend, Vosk or the model are
    unavailable.
    """
    rate = int(samplerate or audio.TARGET_RATE)
    sd = audio._import_sounddevice()
    rec = transcribe._make_recognizer(model_dir, words=False)

    audio_q: "queue.Queue[bytes]" = queue.Queue()

    def _callback(indata, _frames, _time, status):  # runs on PortAudio thread
        # ``indata`` is raw bytes because we use RawInputStream below.
        audio_q.put(bytes(indata))

    try:
        stream = sd.RawInputStream(
            samplerate=rate, blocksize=blocksize, dtype="int16",
            channels=1, device=device, callback=_callback,
        )
    except Exception as exc:  # noqa: BLE001
        raise VoiceTypeError(
            f"could not open the microphone: {exc}. Check your input device."
        ) from exc

    last_partial = ""
    try:
        with stream:
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    data = audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if rec.AcceptWaveform(data):
                    text = (json.loads(rec.Result()).get("text") or "").strip()
                    last_partial = ""
                    if text:
                        yield {"type": "final", "text": text}
                else:
                    partial = (json.loads(rec.PartialResult()).get("partial")
                               or "").strip()
                    if partial and partial != last_partial:
                        last_partial = partial
                        yield {"type": "partial", "text": partial}
            # flush whatever is buffered when stopping
            text = (json.loads(rec.FinalResult()).get("text") or "").strip()
            if text:
                yield {"type": "final", "text": text}
    except VoiceTypeError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak a raw traceback
        raise VoiceTypeError(f"dictation error: {exc}") from exc


# ---------------------------------------------------------------------------
# Keystroke injection (Windows only; a safe no-op elsewhere)
# ---------------------------------------------------------------------------
def type_out(text):
    """Inject *text* as keystrokes into the focused window (Windows only).

    On Windows this uses ``SendInput`` with Unicode key events so the text lands
    in whatever application currently has focus.  On other platforms it does
    nothing to the OS and simply returns the text (VoiceType targets the Windows
    desktop; elsewhere the caller can display/copy the text instead).

    Returns the *text* that was (or would have been) typed.
    """
    if not text:
        return text
    import sys

    if sys.platform != "win32":
        return text  # no-op off Windows; caller shows/copies the text

    try:
        _send_unicode_win32(text)
    except Exception as exc:  # noqa: BLE001
        raise VoiceTypeError(f"could not send keystrokes: {exc}") from exc
    return text


def _send_unicode_win32(text):
    """Send *text* via the Win32 ``SendInput`` API (imported lazily)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1

    ULONG_PTR = wintypes.WPARAM

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    def _key_events(ch):
        code = ord(ch)
        for flags in (KEYEVENTF_UNICODE,
                      KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            ki = KEYBDINPUT(0, code, flags, 0, 0)
            yield INPUT(INPUT_KEYBOARD, _INPUTunion(ki=ki))

    events = [ev for ch in text for ev in _key_events(ch)]
    if not events:
        return
    n = len(events)
    arr = (INPUT * n)(*events)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        raise OSError(ctypes.get_last_error(), "SendInput did not send all events")


__all__ = ["dictate", "type_out"]
