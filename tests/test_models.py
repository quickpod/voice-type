"""Model catalog / path-resolution / offline-install tests (no real download)."""

import os

import pytest

from voicetype import models
from voicetype.errors import VoiceTypeError


@pytest.fixture
def tmp_models(tmp_path, monkeypatch):
    """Point the models directory at a temp folder for the whole test."""
    root = tmp_path / "models"
    monkeypatch.setattr(models, "models_dir", lambda: str(root))
    return str(root)


def _make_fake_model(root, name):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "conf"), exist_ok=True)
    os.makedirs(os.path.join(d, "am"), exist_ok=True)
    return d


def test_catalog_has_expected_default():
    names = [e["name"] for e in models.list_available()]
    assert "vosk-model-small-en-us-0.15" in names
    entry = models.catalog_entry("vosk-model-small-en-us-0.15")
    assert entry["language"] == "English (US)"
    assert entry["url"].endswith("vosk-model-small-en-us-0.15.zip")
    assert entry["url"].startswith("https://alphacephei.com/vosk/models/")


def test_catalog_entry_unknown_is_none():
    assert models.catalog_entry("nope-not-a-model") is None


def test_model_path_under_models_dir(tmp_models):
    p = models.model_path("vosk-model-small-en-us-0.15")
    assert p == os.path.join(tmp_models, "vosk-model-small-en-us-0.15")


def test_list_installed_and_is_installed(tmp_models):
    assert models.list_installed() == []
    _make_fake_model(tmp_models, "vosk-model-small-en-us-0.15")
    _make_fake_model(tmp_models, "vosk-model-small-fr-0.22")
    assert models.is_installed("vosk-model-small-en-us-0.15")
    assert models.list_installed() == [
        "vosk-model-small-en-us-0.15",
        "vosk-model-small-fr-0.22",
    ]


def test_resolve_model_dir_by_name(tmp_models):
    d = _make_fake_model(tmp_models, "vosk-model-small-en-us-0.15")
    assert models.resolve_model_dir("vosk-model-small-en-us-0.15") == d


def test_resolve_model_dir_default_picks_first(tmp_models):
    _make_fake_model(tmp_models, "vosk-model-small-en-us-0.15")
    assert models.resolve_model_dir(None).endswith("vosk-model-small-en-us-0.15")


def test_resolve_model_dir_explicit_path(tmp_path):
    d = tmp_path / "custom-model"
    (d / "conf").mkdir(parents=True)
    assert models.resolve_model_dir(str(d)) == str(d)


def test_resolve_model_dir_unknown_raises(tmp_models):
    with pytest.raises(VoiceTypeError) as ei:
        models.resolve_model_dir("vosk-model-small-en-us-0.15")
    assert "not installed" in str(ei.value)


def test_resolve_model_dir_none_when_empty_raises(tmp_models):
    with pytest.raises(VoiceTypeError) as ei:
        models.resolve_model_dir(None)
    assert "no speech model" in str(ei.value).lower()


def test_ensure_model_returns_existing(tmp_models):
    d = _make_fake_model(tmp_models, "vosk-model-small-en-us-0.15")
    # already installed -> no network, returns the path
    assert models.ensure_model("vosk-model-small-en-us-0.15") == d


def test_ensure_model_offline_raises_and_cleans(tmp_models, monkeypatch):
    def boom(url, dest, *, progress=None):
        raise VoiceTypeError("could not reach host: offline. Are you online?")

    monkeypatch.setattr(models, "_download", boom)
    with pytest.raises(VoiceTypeError) as ei:
        models.ensure_model("vosk-model-small-en-us-0.15")
    assert "online" in str(ei.value).lower()
    # nothing left half-installed
    assert not models.is_installed("vosk-model-small-en-us-0.15")
    assert not os.path.exists(
        models.model_path("vosk-model-small-en-us-0.15") + ".download.zip")


def test_ensure_model_extracts_local_zip(tmp_models, tmp_path):
    """Exercise the download+extract path with a locally-built zip (no network)."""
    import zipfile

    name = "vosk-model-small-en-us-0.15"
    zpath = tmp_path / "model.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(f"{name}/conf/model.conf", "x")
        zf.writestr(f"{name}/am/final.mdl", "y")

    def fake_download(url, dest, *, progress=None):
        import shutil
        shutil.copyfile(zpath, dest)
        if progress:
            progress(100, 100)

    import voicetype.models as m
    orig = m._download
    m._download = fake_download
    try:
        out = models.ensure_model(name)
    finally:
        m._download = orig
    assert models.is_installed(name)
    assert os.path.isdir(os.path.join(out, "conf"))
