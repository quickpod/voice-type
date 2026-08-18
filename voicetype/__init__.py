"""voicetype -- offline speech-to-text & dictation built on Vosk.

Public API (all offline; the only network use is an explicit model download)::

    from voicetype import transcribe_file, to_srt, ensure_model
    text = transcribe_file("clip.wav", model_dir).text

Design rules that this package guarantees:

* Importing ``voicetype`` (and any submodule) never imports the native speech
  engine (``vosk``) or an audio-capture backend (``sounddevice``) -- those are
  imported lazily inside the functions that need them, so the package and its
  test-suite run on a machine with neither the native libs nor a model present.
* Every recoverable failure is raised as :class:`VoiceTypeError`, so the CLI and
  GUI have a single exception type to present as a clean message.

Missing libraries/models produce a :class:`VoiceTypeError` explaining how to
install Vosk or download a model.
"""

from __future__ import annotations

from .errors import VoiceTypeError
from .transcribe import (
    TranscriptResult,
    to_srt,
    to_txt,
    to_vtt,
    transcribe_file,
    transcribe_stream,
)
from .models import (
    catalog_entry,
    data_dir,
    ensure_model,
    is_installed,
    list_available,
    list_installed,
    model_path,
    models_dir,
    resolve_model_dir,
)
from .audio import (
    list_input_devices,
    read_wav_16k_mono,
    read_wav_info,
)
from .dictate import dictate as live_dictate, type_out

__version__ = "1.0.5"

__all__ = [
    "VoiceTypeError",
    "TranscriptResult",
    "transcribe_file",
    "transcribe_stream",
    "to_srt",
    "to_txt",
    "to_vtt",
    "catalog_entry",
    "data_dir",
    "models_dir",
    "model_path",
    "ensure_model",
    "is_installed",
    "list_available",
    "list_installed",
    "resolve_model_dir",
    "list_input_devices",
    "read_wav_16k_mono",
    "read_wav_info",
    "live_dictate",
    "type_out",
    "__version__",
]
