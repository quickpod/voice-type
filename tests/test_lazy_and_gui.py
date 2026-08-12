"""Prove the package imports (and the CLI/GUI construct) WITHOUT the native
speech engine or an audio backend, and that the GUI is headless-safe."""

import importlib
import sys

import pytest


def _reimport_voicetype(monkeypatch):
    """Drop cached voicetype modules and re-import with vosk/sounddevice
    forced to be unimportable (``sys.modules[name] = None``)."""
    for name in list(sys.modules):
        if name == "voicetype" or name.startswith("voicetype."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "vosk", None)
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    return importlib.import_module("voicetype")


def test_package_imports_without_vosk_or_sounddevice(monkeypatch):
    vt = _reimport_voicetype(monkeypatch)
    assert hasattr(vt, "VoiceTypeError")
    assert hasattr(vt, "transcribe_file")
    # submodules import too
    importlib.import_module("voicetype.transcribe")
    importlib.import_module("voicetype.dictate")
    importlib.import_module("voicetype.audio")
    importlib.import_module("voicetype.models")


def test_gui_imports_without_vosk(monkeypatch):
    _reimport_voicetype(monkeypatch)
    gui = importlib.import_module("voicetype.gui")
    assert callable(gui.main)


def test_cli_parser_builds_without_vosk(monkeypatch):
    _reimport_voicetype(monkeypatch)
    cli = importlib.import_module("voicetype.__main__")
    parser = cli.build_parser()
    args = parser.parse_args(["transcribe", "clip.wav", "--srt", "out.srt"])
    assert args.command == "transcribe"
    assert args.srt == "out.srt"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows CI has a real display; main() would open a window and block")
def test_lazy_vosk_import_raises_voicetypeerror(monkeypatch):
    vt = _reimport_voicetype(monkeypatch)
    transcribe = importlib.import_module("voicetype.transcribe")
    with pytest.raises(vt.VoiceTypeError):
        transcribe._import_vosk()


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows CI has a real display; main() would open a window and block")
def test_lazy_sounddevice_import_raises_voicetypeerror(monkeypatch):
    vt = _reimport_voicetype(monkeypatch)
    audio = importlib.import_module("voicetype.audio")
    with pytest.raises(vt.VoiceTypeError):
        audio._import_sounddevice()


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows CI has a real display; main() would open a window and block")
def test_gui_main_headless_returns_zero():
    """gui.main() must not raise on a headless box (no $DISPLAY)."""
    from voicetype import gui
    rc = gui.main()
    assert rc == 0


def test_type_out_noop_off_windows(monkeypatch):
    from voicetype import dictate
    monkeypatch.setattr(sys, "platform", "linux")
    assert dictate.type_out("hello") == "hello"
