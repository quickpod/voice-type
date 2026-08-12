#!/usr/bin/env python3
r"""VoiceType -- an Aura (QuickOpen design system) GUI on top of ``voicetype``.

A single Aura window with a sidebar (Transcribe, Dictate, Models, About) and a
swappable content panel.  Every operation calls the tested core package (never
re-implements recognition logic) and runs on a background thread so the UI
stays responsive; results are marshalled back with ``self.after`` and reported
in the Aura status bar -- text/paths on success, or the ``VoiceTypeError``
message (never a raw traceback) on failure.

Design goals baked in here (mirrors the QuickOpen house style):
  * built on the vendored ``voicetype/aura.py`` design system, which layers the
    quickopen.ai look (deep space + light) over CustomTkinter.  Runtime deps:
    ``customtkinter`` (+ ``darkdetect``) — declared in requirements.txt; the
    PyInstaller build adds ``--collect-all customtkinter``.
  * Importing this module does nothing.  Only :func:`main` builds a root
    window, and it degrades gracefully (prints a message, returns 0) with no
    display or with customtkinter missing.
  * Frozen-exe safe: bundled assets are resolved via ``sys._MEIPASS`` / the exe
    directory when ``sys.frozen`` is set -- never ``__file__``.
  * The native speech stack (Vosk) and audio backend are imported lazily by the
    core package, so the GUI starts even with neither installed; missing pieces
    surface as an inline VoiceTypeError with guidance.

100% AI-built, open source, published on QuickOpen (quickopen.ai).
"""

from __future__ import annotations

import os
import sys
import threading

# NOTE: tkinter/customtkinter are imported lazily inside main()/build_app so
# that merely importing this module (e.g. during packaging or on a headless CI
# box) never fails.

APP_NAME = "VoiceType"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "VoiceType — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"
ACCENT = "#5b86f7"      # publish/specs/voice-type.json "accent": [91, 134, 247]

AUDIO_TYPES = [
    ("Audio", "*.wav *.flac *.ogg *.mp3 *.m4a *.aiff *.aif"),
    ("WAV files", "*.wav"),
    ("All files", "*.*"),
]

SECTION_DESCRIPTIONS = {
    "transcribe": "Turn an audio or video-audio file into text or subtitles — "
                  "fully offline. Pick a file and a model, then Save as "
                  "TXT / SRT / VTT.",
    "dictate": "Speak into your microphone and see the words appear live. "
               "Copy the text, or type it straight into the focused window "
               "(Windows).",
    "models": "Vosk speech models are downloaded on first use (Apache-2.0). "
              "Install the language(s) you need; everything else stays "
              "offline.",
}


# ---------------------------------------------------------------------------
# Asset / frozen handling
# ---------------------------------------------------------------------------
def asset_path(name):
    """Locate a bundled asset from source OR a PyInstaller one-file build.

    For a frozen exe we look only at ``sys._MEIPASS`` and the executable's own
    directory (never ``__file__``).  From source we also consult the package
    dir, the repo root and the CWD.  Returns an absolute path or ``None``.
    """
    roots = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        roots += [here, os.path.dirname(here), os.getcwd()]
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    return None


def open_in_file_manager(path):
    """Best-effort 'reveal in file manager', guarded on every platform."""
    try:
        folder = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        if hasattr(os, "startfile"):          # Windows
            os.startfile(folder)              # noqa: S606 - intended
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", folder])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False


def open_with_default_app(path):
    """Open a file/URL with the OS default application, guarded."""
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)                # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The app (built lazily; tkinter/customtkinter imported only inside build_app)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to live GUI imports.

    Kept inside a function so this module imports cleanly without a display
    (and without customtkinter installed).  The speech stack (vosk) and audio
    backend (sounddevice) stay lazy too: they are only touched inside the
    worker functions, via the core package.
    """
    import tkinter as tk
    from tkinter import filedialog, ttk
    import customtkinter as ctk

    from . import aura, guiconfig, models, transcribe
    from .errors import VoiceTypeError

    class App(aura.AuraApp):
        def __init__(self):
            super().__init__(
                title=WINDOW_TITLE, app_name=APP_NAME, accent=ACCENT,
                theme=guiconfig.get_theme(),
                icon_png=asset_path("voice-type.png"), version=APP_VERSION,
                tagline="offline speech-to-text",
                on_theme_change=guiconfig.set_theme,
                size=(1080, 680), min_size=(900, 560))

            self._busy = False
            self._img_refs_gui = []     # keep PhotoImage refs alive (app-local)
            self._last_result = None    # last TranscriptResult (for Save as…)
            self._dictation_stop = None
            self._dictation_thread = None
            self._dc_devices = []       # list of (label, index)

            self._set_icon()
            self._build_menu()
            self.add_section("transcribe", "Transcribe", "♪",
                             self._build_transcribe)
            self.add_section("dictate", "Dictate", "◉", self._build_dictate)
            self.add_section("models", "Models", "⛁", self._build_models)
            self.add_section("about", "About", "ℹ", self._build_about)
            self.show("transcribe")
            self.set_status("Ready")
            self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- navigation: keep model combos fresh when a panel is shown
        def show(self, sid):
            super().show(sid)
            if sid in ("transcribe", "dictate"):
                self._refresh_model_combos()

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("voice-type.ico")
                if ico and os.name == "nt":
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("voice-type.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs_gui.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- menu (native menus stay; theme lives in the sidebar toggle too)
        def _build_menu(self):
            bar = tk.Menu(self)
            filem = tk.Menu(bar, tearoff=0)
            filem.add_command(label="Open audio…", accelerator="Ctrl+O",
                              command=self._open_audio)
            filem.add_separator()
            filem.add_command(label="Exit", command=self._on_close)
            bar.add_cascade(label="File", menu=filem)

            viewm = tk.Menu(bar, tearoff=0)
            viewm.add_command(
                label="Toggle dark mode",
                command=lambda: self.set_theme(
                    "light" if self.theme == "dark" else "dark"))
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=lambda: self.show("about"))
            helpm.add_command(label="Open project page (quickopen.ai)",
                              command=lambda: open_with_default_app(PROJECT_URL))
            bar.add_cascade(label="Help", menu=helpm)
            self.configure(menu=bar)
            self.bind_all("<Control-o>", lambda e: self._open_audio())

        def _open_audio(self):
            p = filedialog.askopenfilename(title="Open audio",
                                           filetypes=AUDIO_TYPES)
            if p:
                guiconfig.add_recent(p)
                self.show("transcribe")
                if hasattr(self, "_tr_input_entry"):
                    self._fill(self._tr_input_entry, p)

        # ---- small helpers
        @staticmethod
        def _fill(entry, text):
            entry.delete(0, "end")
            if text:
                entry.insert(0, text)

        # ---- background operation runner
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            """Run ``work()`` off the UI thread; call ``on_ok(result)`` back on it.

            Errors are shown in the status bar (VoiceTypeError message, or a
            generic note), never as a traceback.  Refuses a second op while
            one is in flight.
            """
            if self._busy:
                self.set_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self.set_status(busy, kind="working")

            def run():
                try:
                    res, err = work(), None
                except VoiceTypeError as ex:
                    res, err = None, str(ex)
                except Exception as ex:  # never leak a traceback to the user
                    res, err = None, f"Unexpected error: {ex}"
                self.after(0, lambda: finish(res, err))

            def finish(res, err):
                self._busy = False
                if button is not None:
                    try:
                        button.state(["!disabled"])
                    except Exception:
                        pass
                if err is not None:
                    self.set_error(err)
                    return
                self.set_status("Done", kind="ok")
                try:
                    on_ok(res)
                except Exception as ex:
                    self.set_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- model helpers
        def _installed_models(self):
            try:
                return models.list_installed()
            except Exception:
                return []

        def _refresh_model_combos(self):
            installed = self._installed_models()
            values = installed or ["(no model installed — see Models)"]
            for combo_attr, var_attr in (("_tr_model_combo", "_tr_model"),
                                         ("_dc_model_combo", "_dc_model")):
                combo = getattr(self, combo_attr, None)
                if combo is None:
                    continue
                combo.configure(values=values)
                var = getattr(self, var_attr)
                if installed:
                    want = guiconfig.get_last_model()
                    if var.get() not in installed:
                        var.set(want if want in installed else installed[0])
                else:
                    var.set(values[0])

        # =================================================================
        # Section: Transcribe
        # =================================================================
        def _build_transcribe(self, frame):
            aura.Caption(frame, SECTION_DESCRIPTIONS["transcribe"],
                         wraplength=760, justify="left").pack(
                anchor="w", pady=(0, 10))

            card = aura.Card(frame, title="Audio file")
            card.pack(fill="x", pady=(0, 14))
            row = ctk.CTkFrame(card.body, fg_color="transparent")
            row.pack(fill="x", pady=(0, 8))
            # no textvariable: CTkEntry placeholders only work without one
            self._tr_input_entry = aura.AuraEntry(
                row, placeholder="Audio file to transcribe…")
            self._tr_input_entry.pack(side="left", fill="x", expand=True,
                                      padx=(0, 8))
            aura.AuraButton(row, "Browse…", kind="secondary",
                            command=self._tr_browse).pack(side="left")

            row2 = ctk.CTkFrame(card.body, fg_color="transparent")
            row2.pack(fill="x")
            self._tr_model = tk.StringVar()
            self._tr_model_combo = aura.AuraCombo(
                row2, variable=self._tr_model, values=[], state="readonly",
                width=280)
            self._tr_model_combo.pack(side="left", padx=(0, 14))
            self._tr_words = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(row2, text="Word timestamps",
                            variable=self._tr_words,
                            font=aura.font()).pack(side="left")
            self._tr_run_btn = aura.AuraButton(row2, "Transcribe",
                                               command=self._tr_run)
            self._tr_run_btn.pack(side="right")

            tcard = aura.Card(frame, title="Transcript")
            tcard.pack(fill="both", expand=True)
            box = ctk.CTkFrame(tcard.body, fg_color="transparent")
            box.pack(fill="both", expand=True)
            self._tr_text = tk.Text(box, wrap="word", height=8, width=20,
                                    undo=True, relief="flat",
                                    font=aura.font(11))
            sb = ttk.Scrollbar(box, orient="vertical",
                               command=self._tr_text.yview)
            self._tr_text.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._tr_text.pack(side="left", fill="both", expand=True)
            aura.track(self._tr_text, "text")

            saverow = ctk.CTkFrame(tcard.body, fg_color="transparent")
            saverow.pack(fill="x", pady=(10, 0))
            aura.AuraButton(saverow, "Save as TXT…", kind="secondary",
                            command=lambda: self._tr_save("txt")).pack(
                side="left")
            aura.AuraButton(saverow, "Save as SRT…", kind="secondary",
                            command=lambda: self._tr_save("srt")).pack(
                side="left", padx=(8, 0))
            aura.AuraButton(saverow, "Save as VTT…", kind="secondary",
                            command=lambda: self._tr_save("vtt")).pack(
                side="left", padx=(8, 0))
            aura.AuraButton(saverow, "Copy", kind="ghost",
                            command=self._tr_copy).pack(side="right")

        def _tr_browse(self):
            p = filedialog.askopenfilename(title="Choose audio",
                                           filetypes=AUDIO_TYPES)
            if p:
                self._fill(self._tr_input_entry, p)

        def _tr_run(self):
            path = self._tr_input_entry.get().strip()
            model = self._tr_model.get().strip()
            words = bool(self._tr_words.get())
            if not path:
                self.set_error("Choose an audio file first.")
                return
            if model not in self._installed_models():
                self.set_error("No model installed — open the Models tab to "
                               "download one.")
                return

            def work():
                model_dir = models.resolve_model_dir(model)
                return transcribe.transcribe_file(path, model_dir, words=words)

            def done(result):
                self._last_result = result
                self._tr_text.delete("1.0", "end")
                self._tr_text.insert("1.0",
                                     result.text or "(no speech detected)")
                guiconfig.set_last_model(model)
                self.set_success(f"Transcribed {os.path.basename(path)} "
                                 f"({len(result.segments)} segments).")

            self._bg(work, done, button=self._tr_run_btn,
                     busy="Transcribing…")

        def _tr_save(self, kind):
            if self._last_result is None:
                self.set_error("Nothing to save yet — run Transcribe first.")
                return
            ext = {"txt": ".txt", "srt": ".srt", "vtt": ".vtt"}[kind]
            p = filedialog.asksaveasfilename(
                title=f"Save as {kind.upper()}", defaultextension=ext,
                filetypes=[(f"{kind.upper()} files", "*" + ext),
                           ("All files", "*.*")])
            if not p:
                return
            if kind == "txt":
                data = transcribe.to_txt(self._last_result) + "\n"
            elif kind == "srt":
                data = transcribe.to_srt(self._last_result)
            else:
                data = transcribe.to_vtt(self._last_result)
            try:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(data)
                self.set_success(f"Saved {os.path.basename(p)}")
            except Exception as ex:
                self.set_error(f"Could not save: {ex}")

        def _tr_copy(self):
            text = self._tr_text.get("1.0", "end").strip()
            if text:
                self.clipboard_clear()
                self.clipboard_append(text)
                self.set_success("Copied transcript to clipboard.")

        # =================================================================
        # Section: Dictate
        # =================================================================
        def _build_dictate(self, frame):
            aura.Caption(frame, SECTION_DESCRIPTIONS["dictate"],
                         wraplength=760, justify="left").pack(
                anchor="w", pady=(0, 10))

            card = aura.Card(frame, title="Microphone & model")
            card.pack(fill="x", pady=(0, 14))

            row = ctk.CTkFrame(card.body, fg_color="transparent")
            row.pack(fill="x", pady=(0, 8))
            aura.Caption(row, "Model").pack(side="left", padx=(0, 8))
            self._dc_model = tk.StringVar()
            self._dc_model_combo = aura.AuraCombo(
                row, variable=self._dc_model, values=[], state="readonly",
                width=280)
            self._dc_model_combo.pack(side="left")

            row2 = ctk.CTkFrame(card.body, fg_color="transparent")
            row2.pack(fill="x", pady=(0, 8))
            aura.Caption(row2, "Microphone").pack(side="left", padx=(0, 8))
            self._dc_device = tk.StringVar()
            self._dc_device_combo = aura.AuraCombo(
                row2, variable=self._dc_device, values=[], state="readonly",
                width=280)
            self._dc_device_combo.pack(side="left", padx=(0, 8))
            aura.AuraButton(row2, "Refresh", kind="secondary",
                            command=self._dc_refresh_devices).pack(side="left")

            row3 = ctk.CTkFrame(card.body, fg_color="transparent")
            row3.pack(fill="x")
            self._dc_type = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(
                row3, variable=self._dc_type, font=aura.font(),
                text="Type into the focused window (Windows only)").pack(
                side="left")
            self._dc_start_btn = aura.AuraButton(row3, "Start",
                                                 command=self._dc_start)
            self._dc_start_btn.pack(side="right")
            self._dc_stop_btn = aura.AuraButton(row3, "Stop", kind="secondary",
                                                command=self._dc_stop,
                                                state="disabled")
            self._dc_stop_btn.pack(side="right", padx=(0, 8))

            tcard = aura.Card(frame, title="Dictation")
            tcard.pack(fill="both", expand=True)
            box = ctk.CTkFrame(tcard.body, fg_color="transparent")
            box.pack(fill="both", expand=True)
            self._dc_text = tk.Text(box, wrap="word", height=6, width=20,
                                    relief="flat", font=aura.font(11))
            sb = ttk.Scrollbar(box, orient="vertical",
                               command=self._dc_text.yview)
            self._dc_text.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._dc_text.pack(side="left", fill="both", expand=True)
            aura.track(self._dc_text, "text")

            self._dc_partial = aura.Caption(tcard.body, "", anchor="w",
                                            wraplength=720, justify="left")
            self._dc_partial.pack(fill="x", pady=(6, 0))

            bottom = ctk.CTkFrame(tcard.body, fg_color="transparent")
            bottom.pack(fill="x", pady=(8, 0))
            aura.AuraButton(bottom, "Copy", kind="secondary",
                            command=self._dc_copy).pack(side="right")
            aura.AuraButton(
                bottom, "Clear", kind="ghost",
                command=lambda: self._dc_text.delete("1.0", "end")).pack(
                side="right", padx=(0, 8))

            self._dc_refresh_devices()

        def _dc_refresh_devices(self):
            from . import audio
            try:
                devs = audio.list_input_devices()
                self._dc_devices = [(d["name"], d["index"]) for d in devs]
                labels = [name for name, _ in self._dc_devices] or ["(default)"]
                self._dc_device_combo.configure(values=labels)
                if labels:
                    default = next((n for n, i in self._dc_devices
                                    for d in devs
                                    if d["index"] == i and d["default"]),
                                   labels[0])
                    self._dc_device.set(default)
            except VoiceTypeError as ex:
                self._dc_devices = []
                self._dc_device_combo.configure(values=["(no audio backend)"])
                self._dc_device.set("(no audio backend)")
                self.set_error(str(ex))

        def _dc_selected_device(self):
            label = self._dc_device.get()
            for name, index in self._dc_devices:
                if name == label:
                    return index
            return None

        def _dc_start(self):
            from . import dictate
            model = self._dc_model.get().strip()
            if model not in self._installed_models():
                self.set_error("No model installed — open the Models tab to "
                               "download one.")
                return
            device = self._dc_selected_device()
            type_out = bool(self._dc_type.get())

            self._dictation_stop = threading.Event()
            stop = self._dictation_stop
            self._dc_start_btn.configure(state="disabled")
            self._dc_stop_btn.configure(state="normal")
            self.set_status("Listening…", kind="working")
            guiconfig.set_last_model(model)

            def worker():
                try:
                    model_dir = models.resolve_model_dir(model)
                    for event in dictate.dictate(model_dir, device=device,
                                                 stop_event=stop):
                        self.after(0, lambda e=event: self._dc_event(e,
                                                                     type_out))
                except VoiceTypeError as ex:
                    self.after(0, lambda: self._dc_finished(str(ex)))
                    return
                except Exception as ex:  # pragma: no cover - defensive
                    self.after(0, lambda: self._dc_finished(
                        f"Unexpected error: {ex}"))
                    return
                self.after(0, lambda: self._dc_finished(None))

            self._dictation_thread = threading.Thread(target=worker,
                                                      daemon=True)
            self._dictation_thread.start()

        def _dc_event(self, event, type_out):
            from . import dictate
            if event["type"] == "partial":
                self._dc_partial.configure(text="… " + event["text"])
            else:
                self._dc_partial.configure(text="")
                self._dc_text.insert("end", event["text"] + " ")
                self._dc_text.see("end")
                if type_out:
                    try:
                        dictate.type_out(event["text"] + " ")
                    except VoiceTypeError as ex:
                        self.set_error(str(ex))

        def _dc_stop(self):
            if self._dictation_stop is not None:
                self._dictation_stop.set()
            self._dc_stop_btn.configure(state="disabled")
            self.set_status("Stopping…", kind="working")

        def _dc_finished(self, err):
            self._dc_partial.configure(text="")
            self._dc_start_btn.configure(state="normal")
            self._dc_stop_btn.configure(state="disabled")
            if err:
                self.set_error(err)
            else:
                self.set_success("Dictation stopped.")

        def _dc_copy(self):
            text = self._dc_text.get("1.0", "end").strip()
            if text:
                self.clipboard_clear()
                self.clipboard_append(text)
                self.set_success("Copied dictation to clipboard.")

        # =================================================================
        # Section: Models
        # =================================================================
        def _build_models(self, frame):
            aura.Caption(frame, SECTION_DESCRIPTIONS["models"],
                         wraplength=760, justify="left").pack(
                anchor="w", pady=(0, 10))

            top = ctk.CTkFrame(frame, fg_color="transparent")
            top.pack(fill="both", expand=True)
            cols = ("language", "size", "status")
            self._md_tree = ttk.Treeview(top, columns=cols,
                                         show="tree headings",
                                         selectmode="browse", height=12)
            self._md_tree.heading("#0", text=aura.spaced("Model"), anchor="w")
            self._md_tree.heading("language", text=aura.spaced("Language"),
                                  anchor="w")
            self._md_tree.heading("size", text=aura.spaced("Size"),
                                  anchor="w")
            self._md_tree.heading("status", text=aura.spaced("Status"),
                                  anchor="w")
            self._md_tree.column("#0", width=280)
            self._md_tree.column("language", width=130)
            self._md_tree.column("size", width=90, anchor="center")
            self._md_tree.column("status", width=100, anchor="center")
            sb = ttk.Scrollbar(top, orient="vertical",
                               command=self._md_tree.yview)
            self._md_tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._md_tree.pack(side="left", fill="both", expand=True)

            ctrl = ctk.CTkFrame(frame, fg_color="transparent")
            ctrl.pack(fill="x", pady=(12, 0))
            self._md_install_btn = aura.AuraButton(
                ctrl, "Install selected", command=self._md_install_selected)
            self._md_install_btn.pack(side="left")
            aura.AuraButton(ctrl, "Refresh", kind="secondary",
                            command=self._md_refresh).pack(side="left",
                                                           padx=(8, 0))
            aura.AuraButton(
                ctrl, "Open models folder", kind="ghost",
                command=lambda: open_in_file_manager(models.models_dir())
                ).pack(side="left", padx=(8, 0))
            self._md_progress = aura.ProgressBar(ctrl, width=220)
            self._md_progress.set(0)
            self._md_progress.pack(side="right")

            self._md_refresh()

        def _md_refresh(self):
            tree = self._md_tree
            tree.delete(*tree.get_children())
            installed = set(self._installed_models())
            seen = set()
            for e in models.list_available():
                seen.add(e["name"])
                status = "Installed" if e["name"] in installed else "Available"
                tree.insert("", "end", iid=e["name"], text=e["name"],
                            values=(e["language"], e["size"], status))
            # any installed-but-not-catalog models
            for name in sorted(installed - seen):
                tree.insert("", "end", iid=name, text=name,
                            values=("(custom)", "-", "Installed"))
            self._refresh_model_combos()

        def _md_install_selected(self):
            sel = self._md_tree.selection()
            if not sel:
                self.set_error("Select a model to install.")
                return
            name = sel[0]
            if models.is_installed(name):
                self.set_success(f"{name} is already installed.")
                return

            self._md_install_btn.configure(state="disabled")
            self._md_progress.set(0)
            self.set_status("Downloading…", kind="working")
            self._busy = True

            def progress(done, total):
                # aura.ProgressBar is 0..1, not maximum/value
                frac = (done / total) if total else 0.0
                self.after(0, lambda: self._md_progress.set(min(1.0, frac)))

            def worker():
                try:
                    models.ensure_model(name, progress=progress)
                    err = None
                except VoiceTypeError as ex:
                    err = str(ex)
                except Exception as ex:  # pragma: no cover - defensive
                    err = f"Unexpected error: {ex}"
                self.after(0, lambda: self._md_done(name, err))

            threading.Thread(target=worker, daemon=True).start()

        def _md_done(self, name, err):
            self._busy = False
            self._md_install_btn.configure(state="normal")
            self._md_progress.set(0)
            if err:
                self.set_error(err)
            else:
                self.set_success(f"Installed {name}.")
            self._md_refresh()

        # =================================================================
        # Section: About
        # =================================================================
        def _build_about(self, frame):
            card = aura.Card(frame, title="About VoiceType")
            card.pack(fill="x")
            aura.Heading(card.body, APP_NAME).pack(anchor="w")
            aura.Caption(card.body, f"Version {APP_VERSION}").pack(
                anchor="w", pady=(0, 10))
            ctk.CTkLabel(
                card.body, font=aura.font(), justify="left", anchor="w",
                wraplength=520,
                text="A fast, fully-offline speech-to-text & dictation app "
                     "built on the permissively-licensed Vosk engine.\n\n"
                     "100% AI-built, open source, published on QuickOpen. "
                     "Nothing is ever uploaded anywhere.").pack(anchor="w")
            aura.Caption(card.body,
                         "Licensed under Apache-2.0. Built on Vosk "
                         "(Apache-2.0) and CustomTkinter (MIT).").pack(
                anchor="w", pady=(10, 4))
            aura.AuraButton(card.body, "Project page: quickopen.ai",
                            kind="ghost",
                            command=lambda: open_with_default_app(
                                PROJECT_URL)).pack(anchor="w", pady=(6, 0))

        # ---- close
        def _on_close(self):
            try:
                if self._dictation_stop is not None:
                    self._dictation_stop.set()
            except Exception:
                pass
            self.destroy()

    return App


def main():
    """Entry point: build the root window and run.  Degrades on headless hosts.

    Importing this module does nothing; only this function creates a Tk root.
    With no display (e.g. a server) or without customtkinter installed, it
    prints a friendly note and returns 0 instead of raising.
    """
    try:
        import tkinter as tk
    except Exception as exc:  # tkinter missing entirely
        print(f"{APP_NAME}: a graphical environment with tkinter is required "
              f"to run the GUI ({exc}).")
        return 0

    try:
        App = build_app()
        app = App()
    except ImportError as exc:
        print(f"{APP_NAME}: the GUI needs the 'customtkinter' package "
              f"({exc}). Install it with:  pip install customtkinter")
        return 0
    except tk.TclError as exc:
        print(f"{APP_NAME}: no graphical display available — cannot start the "
              f"GUI here ({exc}). This app is intended for the Windows desktop.")
        return 0
    except Exception as exc:
        print(f"{APP_NAME}: could not start the GUI ({exc}).")
        return 1

    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
