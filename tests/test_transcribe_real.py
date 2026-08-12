"""Optional end-to-end transcription. Skips unless BOTH the vosk native library
and a real model are available -- so the suite stays green on a bare box."""

import numpy as np
import pytest
import soundfile as sf

from voicetype import models, transcribe


def _first_model_dir():
    installed = models.list_installed()
    return models.model_path(installed[0]) if installed else None


def test_real_transcribe_if_model_present(tmp_path):
    pytest.importorskip("vosk", reason="vosk native library not installed")
    model_dir = _first_model_dir()
    if not model_dir:
        pytest.skip("no Vosk model installed (run 'voicetype models install ...')")

    # a short silent clip is enough to exercise the pipeline end-to-end
    rate = 16000
    silence = np.zeros(rate, dtype="float32")
    wav = tmp_path / "silence.wav"
    sf.write(str(wav), silence, rate)

    result = transcribe.transcribe_file(str(wav), model_dir)
    assert isinstance(result, transcribe.TranscriptResult)
    assert isinstance(result.text, str)
    # exporters run on whatever came back
    assert isinstance(transcribe.to_srt(result), str)
