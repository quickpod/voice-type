"""Error types for voicetype."""


class VoiceTypeError(Exception):
    """Raised for any recoverable failure in a voicetype operation.

    All public functions raise this (and only this) on failure so callers
    -- including the CLI and the GUI -- have a single exception to catch and
    show as a clean message instead of a traceback.  Missing native libraries
    (``vosk``, an audio backend) and missing speech models are surfaced through
    this type with guidance on how to fix them.
    """
