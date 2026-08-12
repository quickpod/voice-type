r"""Tiny JSON-backed config for the VoiceType GUI.

Stores just what the UI needs and never raises: the chosen theme
("light"/"dark"), the last-used model name, and a short list of recent input
files.  On Windows the file lives at ``%LOCALAPPDATA%\VoiceType\config.json``;
elsewhere it falls back to ``~/.voicetype/config.json``.  Every function is
defensive -- a corrupt or unreadable config must never stop the app starting.
"""

from __future__ import annotations

import json
import os

APP_DIRNAME = "VoiceType"
CONFIG_NAME = "config.json"
MAX_RECENT = 10
VALID_THEMES = ("light", "dark")


def config_dir():
    r"""Directory that holds the config file (``%LOCALAPPDATA%\VoiceType``)."""
    local = os.environ.get("LOCALAPPDATA")
    if local and os.name == "nt":
        return os.path.join(local, APP_DIRNAME)
    return os.path.join(os.path.expanduser("~"), "." + APP_DIRNAME.lower())


def config_path():
    return os.path.join(config_dir(), CONFIG_NAME)


def _defaults():
    return {"theme": "light", "last_model": "", "recent": []}


def load():
    """Return the config dict, always with theme/last_model/recent keys."""
    cfg = _defaults()
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            theme = data.get("theme")
            if theme in VALID_THEMES:
                cfg["theme"] = theme
            last = data.get("last_model")
            if isinstance(last, str):
                cfg["last_model"] = last
            recent = data.get("recent")
            if isinstance(recent, list):
                cfg["recent"] = [p for p in recent if isinstance(p, str)][:MAX_RECENT]
    except Exception:
        pass  # missing/corrupt -> defaults; never fatal
    return cfg


def save(cfg):
    """Persist *cfg* (best-effort; failures are swallowed)."""
    try:
        os.makedirs(config_dir(), exist_ok=True)
        clean = {
            "theme": cfg.get("theme") if cfg.get("theme") in VALID_THEMES else "light",
            "last_model": cfg.get("last_model") if isinstance(
                cfg.get("last_model"), str) else "",
            "recent": [p for p in cfg.get("recent", []) if isinstance(p, str)][:MAX_RECENT],
        }
        tmp = config_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, indent=2)
        os.replace(tmp, config_path())
    except Exception:
        pass


def get_theme():
    return load().get("theme", "light")


def set_theme(theme):
    if theme not in VALID_THEMES:
        return
    cfg = load()
    cfg["theme"] = theme
    save(cfg)


def get_last_model():
    return load().get("last_model", "")


def set_last_model(name):
    if not isinstance(name, str):
        return
    cfg = load()
    cfg["last_model"] = name
    save(cfg)


def get_recent():
    return load().get("recent", [])


def add_recent(path):
    """Push *path* to the front of the recent list (most-recent-first)."""
    if not path:
        return
    try:
        ap = os.path.abspath(path)
    except Exception:
        ap = path
    cfg = load()
    recent = [p for p in cfg.get("recent", []) if _abs(p) != ap]
    recent.insert(0, ap)
    cfg["recent"] = recent[:MAX_RECENT]
    save(cfg)


def clear_recent():
    cfg = load()
    cfg["recent"] = []
    save(cfg)


def _abs(p):
    try:
        return os.path.abspath(p)
    except Exception:
        return p
