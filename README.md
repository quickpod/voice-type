# VoiceType

A fast, **offline**, **100% open-source** offline speech-to-text & subtitles for Windows. Nothing is uploaded anywhere. Built entirely by AI with human testing and guidance, and published on [QuickOpen](https://quickopen.ai/projects/voice-type).

> **100% AI-built and open source.** Apache-2.0.

## What it does

Transcribe audio and video to text completely offline using the permissively-licensed Vosk engine — no cloud, no API keys. Generate and edit SRT/VTT subtitles with timestamps, transcribe recordings and meetings, and export plain text. Language models are downloaded on first use (Apache-2.0).

## Features

- **Offline transcription** — turn WAV/FLAC/OGG (any sample rate, mono or stereo) into text. Audio is downmixed to mono and resampled to 16 kHz automatically.
- **Subtitles & text export** — save as **SRT**, **WebVTT** or plain **TXT**, with optional per-word timestamps.
- **Live dictation** — speak into your microphone and watch partial/final text appear; copy it, or type it straight into the focused window on Windows.
- **Model manager** — browse a curated catalog of Vosk models, install the languages you need with a progress bar, and see what's already on disk.
- **Desktop GUI + CLI** — a dark-mode tkinter app (pure standard library, no heavy GUI deps) and a scriptable command line share the same tested core.
- **Truly private** — the only time VoiceType touches the network is an explicit, user-triggered model download. Everything else is 100% local.

## Install

Download **`VoiceType-Setup.exe`** from the [QuickOpen page](https://quickopen.ai/projects/voice-type) or the [GitHub release](https://github.com/quickpod/voice-type/releases/latest) and double-click it. It installs per-user, adds Desktop and Start Menu shortcuts, and can optionally trust the QuickOpen Root CA. Authenticode-signed by the QuickOpen Code Signing CA — verify at [quickopen.ai/trust](https://quickopen.ai/trust).

## Run from source

```sh
pip install -r requirements.txt
python voice_type_app.py          # GUI
python -m voicetype --help    # CLI
```

## CLI examples

```sh
# List installed + downloadable models
python -m voicetype models list

# Download a model (the only network use; ~40 MB)
python -m voicetype models install vosk-model-small-en-us-0.15

# Transcribe to the terminal
python -m voicetype transcribe meeting.wav

# Export subtitles / text (pick a model by name, add word timestamps)
python -m voicetype transcribe talk.wav --model vosk-model-small-en-us-0.15 --srt talk.srt --words
python -m voicetype transcribe talk.wav --vtt talk.vtt
python -m voicetype transcribe talk.wav --txt talk.txt

# Live dictation to the terminal (Ctrl+C to stop); --type sends keystrokes on Windows
python -m voicetype dictate --model vosk-model-small-en-us-0.15
```

If no model is installed, every command exits cleanly with a friendly message telling you exactly what to install — never a traceback.

## Models (offline Vosk — download on first use)

VoiceType uses the **Vosk** engine (Apache-2.0). Speech recognition models are **not bundled** — they are downloaded on first use from the official [Vosk model list](https://alphacephei.com/vosk/models) (Apache-2.0) into your user profile, keeping the installer small and the licensing clean.

- Models live under `%LOCALAPPDATA%\VoiceType\models\<name>` on Windows (`~/.voicetype/models/<name>` elsewhere).
- Install from the **Models** tab in the app (with a progress bar) or via `voicetype models install <name>`.
- Small models (~40 MB) are great for dictation; larger models trade size for accuracy. Many languages are available — English (US/UK), French, German, Spanish, Italian, Portuguese, Russian, Dutch, Chinese, Hindi, Japanese and more.
- Downloading is the **only** time VoiceType uses the network, and it only ever happens when you explicitly ask for a model.

## License

Apache-2.0 — see [LICENSE](LICENSE). A 100% AI-built project published on QuickOpen.
