"""Command-line interface: ``python -m voicetype <command> ...``.

Commands
--------
* ``models list``                 -- show installed + available Vosk models
* ``models install <name>``       -- download & unpack a model (only net use)
* ``transcribe <wav> [...]``      -- transcribe audio to text / SRT / VTT / TXT
* ``dictate [--model NAME]``      -- live microphone dictation (prints text)

Every command exits cleanly (code 1, no traceback) on a
:class:`VoiceTypeError` -- including the friendly "install Vosk / download a
model" guidance when the native library or a model is missing.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import VoiceTypeError


# --- command handlers -------------------------------------------------------
def cmd_models_list(a):
    from . import models

    installed = set(models.list_installed())
    print("Installed models:")
    if installed:
        for name in sorted(installed):
            print(f"  * {name}   ({models.model_path(name)})")
    else:
        print("  (none yet -- run 'voicetype models install <name>')")

    print("\nAvailable to download (curated from alphacephei.com/vosk/models):")
    for e in models.list_available():
        mark = "installed" if e["name"] in installed else e["size"]
        print(f"  {e['name']:<32} {e['language']:<16} {mark}")
        if e["note"]:
            print(f"      {e['note']}")


def cmd_models_install(a):
    from . import models

    if models.is_installed(a.name):
        print(f"Model {a.name!r} is already installed at {models.model_path(a.name)}")
        return

    last = {"pct": -1}

    def progress(done, total):
        if not total:
            return
        pct = int(done * 100 / total)
        if pct != last["pct"] and pct % 5 == 0:
            last["pct"] = pct
            mb = total / (1024 * 1024)
            sys.stderr.write(f"\rDownloading {a.name}: {pct:3d}%  ({mb:.0f} MB)")
            sys.stderr.flush()

    print(f"Installing {a.name} ...")
    path = models.ensure_model(a.name, progress=progress)
    sys.stderr.write("\r" + " " * 60 + "\r")
    sys.stderr.flush()
    print(f"Installed -> {path}")


def cmd_transcribe(a):
    from . import models, transcribe

    model_dir = models.resolve_model_dir(a.model)
    result = transcribe.transcribe_file(a.input, model_dir, words=a.words)

    wrote = False
    if a.srt:
        _write(a.srt, transcribe.to_srt(result))
        print(f"Wrote SRT -> {a.srt} ({len(result.segments)} segments)")
        wrote = True
    if a.vtt:
        _write(a.vtt, transcribe.to_vtt(result))
        print(f"Wrote VTT -> {a.vtt} ({len(result.segments)} segments)")
        wrote = True
    if a.txt:
        _write(a.txt, transcribe.to_txt(result) + "\n")
        print(f"Wrote text -> {a.txt}")
        wrote = True
    if not wrote:
        sys.stdout.write(result.text + "\n")


def cmd_dictate(a):
    from . import dictate, models

    model_dir = models.resolve_model_dir(a.model)
    print("Listening... press Ctrl+C to stop.", file=sys.stderr)
    try:
        for event in dictate.dictate(model_dir, device=a.device):
            if event["type"] == "final":
                line = event["text"]
                if a.type:
                    dictate.type_out(line + " ")
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            else:
                sys.stderr.write("\r… " + event["text"][:70])
                sys.stderr.flush()
    except KeyboardInterrupt:
        sys.stderr.write("\nStopped.\n")


def _write(path, text):
    import os

    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# --- parser -----------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="voicetype",
        description="Offline speech-to-text & dictation using the permissively "
        "licensed Vosk engine. Models are downloaded on first use.",
    )
    p.add_argument("--version", action="version",
                   version=f"VoiceType {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # models
    m = sub.add_parser("models", help="list or install speech models")
    msub = m.add_subparsers(dest="models_command", required=True)
    ml = msub.add_parser("list", help="list installed + available models")
    ml.set_defaults(func=cmd_models_list)
    mi = msub.add_parser("install", help="download & unpack a model")
    mi.add_argument("name", help="model name, e.g. vosk-model-small-en-us-0.15")
    mi.set_defaults(func=cmd_models_install)

    # transcribe
    t = sub.add_parser("transcribe", help="transcribe an audio file")
    t.add_argument("input", help="path to an audio file (WAV/FLAC/OGG)")
    t.add_argument("--model", help="model name or path (default: first installed)")
    t.add_argument("--srt", metavar="OUT", help="write SRT subtitles to OUT")
    t.add_argument("--vtt", metavar="OUT", help="write WebVTT subtitles to OUT")
    t.add_argument("--txt", metavar="OUT", help="write plain text to OUT")
    t.add_argument("--words", action="store_true",
                   help="include per-word timestamps in segments")
    t.set_defaults(func=cmd_transcribe)

    # dictate
    d = sub.add_parser("dictate", help="live microphone dictation")
    d.add_argument("--model", help="model name or path (default: first installed)")
    d.add_argument("--device", type=int, default=None,
                   help="input device index (see 'models'/your OS settings)")
    d.add_argument("--type", action="store_true",
                   help="type recognized text into the focused window (Windows)")
    d.set_defaults(func=cmd_dictate)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except VoiceTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
