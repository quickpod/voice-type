r"""Vosk speech-model management for VoiceType.

Speech recognition models are **not bundled** with the app -- they are the only
thing VoiceType ever downloads, and only when the user explicitly asks for one
(``models install`` / the GUI "Install" button).  Everything else is 100%
offline.

Models live under a per-user data directory::

    %LOCALAPPDATA%\VoiceType\models\<name>     (Windows)
    ~/.voicetype/models/<name>                 (elsewhere)

The catalog below is a small curated subset of the official Vosk model list
(https://alphacephei.com/vosk/models).  Each entry names the model, its
language, an approximate download size and the direct ``.zip`` URL.  Downloads
use the Python standard library only (``urllib`` + ``zipfile``) so importing
this module never pulls in a third-party HTTP dependency.
"""

from __future__ import annotations

import os
import shutil
import zipfile

from .errors import VoiceTypeError

APP_DIRNAME = "VoiceType"
MODELS_SUBDIR = "models"

# Base URL for official Vosk model zips (mirrors vosk.MODEL_PRE_URL).
MODEL_BASE_URL = "https://alphacephei.com/vosk/models/"


def _entry(name, language, size, note=""):
    return {
        "name": name,
        "language": language,
        "size": size,
        "note": note,
        "url": MODEL_BASE_URL + name + ".zip",
    }


# Curated catalog -- small "everyday" models first, then larger/accurate ones.
CATALOG = [
    _entry("vosk-model-small-en-us-0.15", "English (US)", "40 MB",
           "Lightweight US English; great default for dictation."),
    _entry("vosk-model-en-us-0.22", "English (US)", "1.8 GB",
           "Large, higher-accuracy US English."),
    _entry("vosk-model-small-en-gb-0.15", "English (UK)", "40 MB",
           "Lightweight UK English."),
    _entry("vosk-model-small-fr-0.22", "French", "41 MB", "Lightweight French."),
    _entry("vosk-model-small-de-0.15", "German", "45 MB", "Lightweight German."),
    _entry("vosk-model-small-es-0.42", "Spanish", "39 MB", "Lightweight Spanish."),
    _entry("vosk-model-small-it-0.22", "Italian", "48 MB", "Lightweight Italian."),
    _entry("vosk-model-small-pt-0.3", "Portuguese", "31 MB", "Lightweight Portuguese."),
    _entry("vosk-model-small-ru-0.22", "Russian", "45 MB", "Lightweight Russian."),
    _entry("vosk-model-small-nl-0.22", "Dutch", "39 MB", "Lightweight Dutch."),
    _entry("vosk-model-small-cn-0.22", "Chinese", "42 MB", "Lightweight Chinese."),
    _entry("vosk-model-small-hi-0.22", "Hindi", "42 MB", "Lightweight Hindi."),
    _entry("vosk-model-small-ja-0.22", "Japanese", "48 MB", "Lightweight Japanese."),
]

# Fast lookup by name.
_BY_NAME = {e["name"]: e for e in CATALOG}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def data_dir():
    r"""Per-user data directory (``%LOCALAPPDATA%\VoiceType`` on Windows)."""
    local = os.environ.get("LOCALAPPDATA")
    if local and os.name == "nt":
        return os.path.join(local, APP_DIRNAME)
    return os.path.join(os.path.expanduser("~"), "." + APP_DIRNAME.lower())


def models_dir():
    """Directory that holds installed model folders (created on demand)."""
    return os.path.join(data_dir(), MODELS_SUBDIR)


def model_path(name):
    """Absolute path where model *name* is (or would be) installed."""
    return os.path.join(models_dir(), name)


# ---------------------------------------------------------------------------
# Catalog / listing
# ---------------------------------------------------------------------------
def list_available():
    """Return the curated catalog (a list of dicts; safe to mutate the copy)."""
    return [dict(e) for e in CATALOG]


def catalog_entry(name):
    """Return the catalog entry for *name*, or ``None`` if it is not curated."""
    e = _BY_NAME.get(name)
    return dict(e) if e else None


_MODEL_MARKERS = ("am", "conf", "ivector", "graph")


def _has_markers(path):
    """True if *path* directly contains a recognizable Vosk model sub-directory."""
    if not os.path.isdir(path):
        return False
    return any(os.path.isdir(os.path.join(path, m)) for m in _MODEL_MARKERS)


def _looks_like_model(path):
    """True if *path* is a directory that resembles an installed Vosk model.

    A Vosk model ships marker sub-directories (``am``/``conf``/...); we accept
    those, and also fall back to "non-empty directory" so a hand-placed custom
    model still resolves.  (Extraction uses the stricter :func:`_has_markers`.)
    """
    if not os.path.isdir(path):
        return False
    if _has_markers(path):
        return True
    try:
        return any(os.scandir(path))
    except OSError:
        return False


def _find_model_root(path):
    """Descend *path* to the directory that actually holds the model files.

    Vosk zips wrap the model in a single top-level folder; collapse that (and
    any accidental double-nesting) so we install the model files directly.
    """
    if _has_markers(path):
        return path
    subdirs = [e.path for e in os.scandir(path) if e.is_dir()]
    for d in subdirs:
        if _has_markers(d):
            return d
    if len(subdirs) == 1:
        return _find_model_root(subdirs[0])
    return None


def is_installed(name):
    """True if model *name* is present under :func:`models_dir`."""
    return _looks_like_model(model_path(name))


def list_installed():
    """Return the sorted names of models currently installed on disk."""
    root = models_dir()
    if not os.path.isdir(root):
        return []
    names = []
    for entry in os.scandir(root):
        if entry.is_dir() and _looks_like_model(entry.path):
            names.append(entry.name)
    return sorted(names)


# ---------------------------------------------------------------------------
# Resolution + install
# ---------------------------------------------------------------------------
def resolve_model_dir(name_or_path=None):
    """Resolve a usable model directory from a name, a path, or a default.

    * A path to an existing model directory is returned as-is.
    * A catalog/installed *name* resolves to its install directory if present.
    * ``None`` picks the first installed model.

    Raises :class:`VoiceTypeError` with download guidance when nothing matches.
    """
    if name_or_path:
        # An explicit filesystem path to an unpacked model wins.
        if os.path.isdir(name_or_path) and _looks_like_model(name_or_path):
            return os.path.abspath(name_or_path)
        if is_installed(name_or_path):
            return model_path(name_or_path)
        installed = list_installed()
        hint = _download_hint(name_or_path)
        if installed:
            hint += f"\nInstalled models: {', '.join(installed)}."
        raise VoiceTypeError(
            f"speech model {name_or_path!r} is not installed.\n{hint}"
        )

    installed = list_installed()
    if installed:
        return model_path(installed[0])
    raise VoiceTypeError(
        "no speech model is installed.\n" + _download_hint(
            "vosk-model-small-en-us-0.15")
    )


def _download_hint(name):
    known = name in _BY_NAME
    lines = [
        f"Install it with:  voicetype models install {name}"
        if known else
        "Install a model with:  voicetype models install "
        "vosk-model-small-en-us-0.15",
        "or download one from https://alphacephei.com/vosk/models and unzip it "
        f"into {models_dir()}.",
    ]
    return "\n".join(lines)


def ensure_model(name, *, progress=None):
    """Ensure model *name* is installed, downloading + unzipping if missing.

    Returns the absolute model directory.  This is the ONLY function in
    VoiceType that touches the network, and it does so only for an explicit
    model name.  *progress* is an optional ``callable(done_bytes, total_bytes)``
    invoked during the download (``total_bytes`` may be 0 if unknown).

    Raises :class:`VoiceTypeError` on any download/extract failure (including
    being offline) with a clear message.
    """
    if is_installed(name):
        return model_path(name)

    entry = _BY_NAME.get(name)
    url = entry["url"] if entry else (MODEL_BASE_URL + name + ".zip")

    target = model_path(name)
    os.makedirs(models_dir(), exist_ok=True)
    tmp_zip = target + ".download.zip"
    tmp_extract = target + ".extract"

    try:
        _download(url, tmp_zip, progress=progress)
        _extract_model(tmp_zip, tmp_extract, name, target)
    except VoiceTypeError:
        _cleanup(tmp_zip, tmp_extract)
        raise
    except Exception as exc:  # noqa: BLE001 - normalise to our error type
        _cleanup(tmp_zip, tmp_extract)
        raise VoiceTypeError(
            f"could not install model {name!r}: {exc}\n"
            "Check your internet connection, or download the model manually "
            f"from https://alphacephei.com/vosk/models and unzip it into "
            f"{models_dir()}."
        ) from exc
    finally:
        _cleanup(tmp_zip, tmp_extract, keep_target=True)

    return target


def _download(url, dest, *, progress=None):
    """Stream *url* to *dest*, reporting progress.  Stdlib ``urllib`` only."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "VoiceType"})
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 - trusted host
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            if progress:
                progress(0, total)
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except urllib.error.HTTPError as exc:
        raise VoiceTypeError(
            f"download failed ({exc.code} {exc.reason}) for {url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise VoiceTypeError(
            f"could not reach {url}: {exc.reason}. Are you online?"
        ) from exc


def _extract_model(zip_path, extract_dir, name, target):
    """Unzip *zip_path* and move the model folder into place at *target*."""
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        raise VoiceTypeError(
            f"the downloaded file for {name!r} is not a valid zip archive."
        ) from exc

    # Vosk zips contain a single top-level folder (usually == name); find the
    # directory that actually holds the model files.
    src = _find_model_root(extract_dir)
    if src is None:
        raise VoiceTypeError(
            f"archive for {name!r} did not contain a recognizable model."
        )

    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    shutil.move(src, target)


def _cleanup(tmp_zip, tmp_extract, keep_target=False):
    for p in (tmp_zip,):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    try:
        if os.path.isdir(tmp_extract):
            shutil.rmtree(tmp_extract, ignore_errors=True)
    except OSError:
        pass


__all__ = [
    "CATALOG",
    "MODEL_BASE_URL",
    "data_dir",
    "models_dir",
    "model_path",
    "list_available",
    "catalog_entry",
    "is_installed",
    "list_installed",
    "resolve_model_dir",
    "ensure_model",
]
