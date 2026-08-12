#!/usr/bin/env python3
r"""VoiceType -- a pure-stdlib tkinter GUI on top of the ``voicetype`` package.

A single main window: a left sidebar (Transcribe, Dictate, Models) and a main
panel that swaps to the selected tool.  Every operation calls the tested core
package (never re-implements recognition logic) and runs on a background thread
so the UI stays responsive; results are marshalled back with ``self.after`` and
reported in a clear inline area -- text/paths on success, or the
``VoiceTypeError`` message (never a raw traceback) on failure.

Design goals baked in here (mirroring the QuickOpen house style):
  * pure standard-library tkinter/ttk -- NO third-party GUI deps.  Dark mode is
    a ttk-style + palette swap.
  * Importing this module does nothing.  Only :func:`main` builds a root window,
    and it degrades gracefully (prints a message, returns 0) with no display.
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

# NOTE: tkinter is imported lazily inside main()/build_app so that merely
# importing this module (e.g. during packaging or on a headless CI box) never
# fails.

APP_NAME = "VoiceType"
APP_VERSION = "1.0.0"
WINDOW_TITLE = "VoiceType — by QuickOpen (quickopen.ai)"
PROJECT_URL = "https://quickopen.ai"

AUDIO_TYPES = [
    ("Audio", "*.wav *.flac *.ogg *.mp3 *.m4a *.aiff *.aif"),
    ("WAV files", "*.wav"),
    ("All files", "*.*"),
]

# (tool_id, label) -- tool_id maps to a _panel_<id> method.
TOOL_TREE = [
    ("Speech", [
        ("transcribe", "Transcribe file"),
        ("dictate", "Dictate (live)"),
    ]),
    ("Setup", [
        ("models", "Models"),
    ]),
]

TOOL_DESCRIPTIONS = {
    "transcribe": "Turn an audio or video-audio file into text or subtitles — "
                  "fully offline. Pick a file and a model, then Save as "
                  "TXT / SRT / VTT.",
    "dictate": "Speak into your microphone and see the words appear live. "
               "Copy the text, or type it straight into the focused window "
               "(Windows).",
    "models": "Vosk speech models are downloaded on first use (Apache-2.0). "
              "Install the language(s) you need; everything else stays offline.",
}

# ---- colour palettes (mirror the QuickOpen palette) -------------------------
PALETTES = {
    "light": {
        "bg": "#f5f7fa", "surface": "#ffffff", "text": "#141820",
        "muted": "#5b6472", "primary": "#2f5fe0", "primary_hi": "#2450c8",
        "entry": "#ffffff", "border": "#d5dae2", "sel": "#2f5fe0",
        "sel_fg": "#ffffff", "trough": "#e2e7ef", "ok": "#1f7a3d",
        "err": "#c0392b",
    },
    "dark": {
        "bg": "#0f1115", "surface": "#1a1e24", "text": "#f1f3f7",
        "muted": "#9aa4b2", "primary": "#5b86f7", "primary_hi": "#7098ff",
        "entry": "#1a1e24", "border": "#2a2f38", "sel": "#5b86f7",
        "sel_fg": "#0f1115", "trough": "#2a2f38", "ok": "#5bd68a",
        "err": "#ff6b5e",
    },
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
# The app (built lazily; tkinter imported only inside build_app/main)
# ---------------------------------------------------------------------------
def build_app():
    """Construct and return the App class bound to a live tkinter import.

    Kept inside a function so this module imports cleanly without a display.
    """
    import tkinter as tk
    from tkinter import filedialog, ttk

    from . import guiconfig, models, transcribe
    from .errors import VoiceTypeError

    FONT = "Segoe UI"

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(WINDOW_TITLE)
            self.geometry("1040x680")
            self.minsize(860, 560)

            self.theme = guiconfig.get_theme()
            self._busy = False
            self._panels = {}          # tool_id -> built frame (lazy)
            self._current = None
            self._tracked = []         # (tk_widget, role) for manual re-theming
            self._img_refs = []        # keep PhotoImage refs alive
            self._last_result = None   # last TranscriptResult (for Save as…)
            self._dictation_stop = None
            self._dictation_thread = None

            self._set_icon()
            self._build_menu()
            self._build_layout()
            self._apply_theme()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(50, self._select_first_tool)

        # ---- assets / icon
        def _set_icon(self):
            try:
                ico = asset_path("voice-type.ico")
                if ico:
                    self.iconbitmap(ico)
                    return
            except Exception:
                pass
            try:
                png = asset_path("voice-type.png")
                if png:
                    img = tk.PhotoImage(file=png)
                    self._img_refs.append(img)
                    self.iconphoto(True, img)
            except Exception:
                pass  # icon is cosmetic; never block launch

        # ---- theming
        def track(self, widget, role):
            self._tracked.append((widget, role))

        def _pal(self):
            return PALETTES[self.theme]

        def _apply_theme(self):
            p = self._pal()
            style = ttk.Style(self)
            try:
                style.theme_use("clam")
            except Exception:
                pass
            self.configure(bg=p["bg"])
            style.configure(".", background=p["bg"], foreground=p["text"],
                            fieldbackground=p["entry"], bordercolor=p["border"],
                            font=(FONT, 10))
            style.configure("TFrame", background=p["bg"])
            style.configure("Sidebar.TFrame", background=p["surface"])
            style.configure("Card.TFrame", background=p["surface"])
            style.configure("TLabel", background=p["bg"], foreground=p["text"])
            style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
            style.configure("Header.TLabel", background=p["bg"], foreground=p["text"],
                            font=(FONT, 15, "bold"))
            style.configure("Sub.TLabel", background=p["bg"], foreground=p["muted"],
                            font=(FONT, 10))
            style.configure("Brand.TLabel", background=p["surface"],
                            foreground=p["text"], font=(FONT, 12, "bold"))
            style.configure("Status.TLabel", background=p["surface"],
                            foreground=p["muted"])
            style.configure("TButton", background=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], focuscolor=p["surface"],
                            padding=(10, 5))
            style.map("TButton",
                      background=[("active", p["trough"]), ("disabled", p["bg"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Accent.TButton", background=p["primary"],
                            foreground="#ffffff", padding=(12, 6))
            style.map("Accent.TButton",
                      background=[("active", p["primary_hi"]),
                                  ("disabled", p["border"])],
                      foreground=[("disabled", p["muted"])])
            style.configure("Toggle.TButton", background=p["surface"],
                            foreground=p["text"], padding=(8, 4))
            for name in ("TEntry", "TSpinbox"):
                style.configure(name, fieldbackground=p["entry"], foreground=p["text"],
                                insertcolor=p["text"], bordercolor=p["border"])
            style.configure("TCombobox", fieldbackground=p["entry"],
                            foreground=p["text"], background=p["surface"],
                            arrowcolor=p["text"])
            style.map("TCombobox",
                      fieldbackground=[("readonly", p["entry"])],
                      foreground=[("readonly", p["text"])])
            style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
            style.map("TCheckbutton", background=[("active", p["bg"])])
            style.configure("Treeview", background=p["surface"],
                            fieldbackground=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], rowheight=24)
            style.map("Treeview", background=[("selected", p["primary"])],
                      foreground=[("selected", p["sel_fg"])])
            style.configure("Sidebar.Treeview", background=p["surface"],
                            fieldbackground=p["surface"])
            style.configure("TProgressbar", background=p["primary"],
                            troughcolor=p["trough"], bordercolor=p["border"])
            style.configure("TScrollbar", background=p["surface"],
                            troughcolor=p["bg"], bordercolor=p["border"],
                            arrowcolor=p["text"])
            style.configure("TSeparator", background=p["border"])

            for widget, role in list(self._tracked):
                try:
                    if role == "listbox":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"],
                                         borderwidth=0)
                    elif role == "text":
                        widget.configure(bg=p["surface"], fg=p["text"],
                                         insertbackground=p["text"],
                                         selectbackground=p["primary"],
                                         selectforeground=p["sel_fg"],
                                         highlightthickness=1,
                                         highlightbackground=p["border"],
                                         borderwidth=0)
                except Exception:
                    pass

        def toggle_theme(self):
            self.theme = "dark" if self.theme == "light" else "light"
            guiconfig.set_theme(self.theme)
            self._apply_theme()
            self._theme_btn.configure(
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")

        # ---- menu
        def _build_menu(self):
            bar = tk.Menu(self)
            filem = tk.Menu(bar, tearoff=0)
            filem.add_command(label="Open audio…", accelerator="Ctrl+O",
                              command=self._open_audio)
            filem.add_separator()
            filem.add_command(label="Exit", command=self._on_close)
            bar.add_cascade(label="File", menu=filem)

            viewm = tk.Menu(bar, tearoff=0)
            viewm.add_command(label="Toggle dark mode", command=self.toggle_theme)
            bar.add_cascade(label="View", menu=viewm)

            helpm = tk.Menu(bar, tearoff=0)
            helpm.add_command(label="About", command=self._about)
            helpm.add_command(label="Open project page (quickopen.ai)",
                              command=lambda: open_with_default_app(PROJECT_URL))
            bar.add_cascade(label="Help", menu=helpm)
            self.configure(menu=bar)
            self.bind_all("<Control-o>", lambda e: self._open_audio())

        def _open_audio(self):
            p = filedialog.askopenfilename(title="Open audio", filetypes=AUDIO_TYPES)
            if p:
                guiconfig.add_recent(p)
                self._select_tool("transcribe")
                panel = self._panels.get("transcribe")
                if panel is not None and hasattr(self, "_tr_input"):
                    self._tr_input.set(p)

        # ---- layout
        def _build_layout(self):
            top = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 8))
            top.pack(fill="x", side="top")
            ttk.Label(top, text="VoiceType", style="Brand.TLabel").pack(side="left")
            ttk.Label(top, style="Status.TLabel",
                      text="  offline · open source · by QuickOpen").pack(side="left")
            self._theme_btn = ttk.Button(
                top, style="Toggle.TButton", command=self.toggle_theme,
                text="☀ Light mode" if self.theme == "dark" else "🌙 Dark mode")
            self._theme_btn.pack(side="right")

            body = ttk.Frame(self, style="TFrame")
            body.pack(fill="both", expand=True)

            side = ttk.Frame(body, style="Sidebar.TFrame", width=210)
            side.pack(side="left", fill="y")
            side.pack_propagate(False)
            self.nav = ttk.Treeview(side, show="tree", selectmode="browse",
                                    style="Sidebar.Treeview")
            self.nav.pack(fill="both", expand=True, padx=6, pady=6)
            self._nav_ids = {}
            for cat, tools in TOOL_TREE:
                cid = self.nav.insert("", "end", text=cat, open=True, tags=("cat",))
                for tid, label in tools:
                    iid = self.nav.insert(cid, "end", text="   " + label)
                    self._nav_ids[iid] = tid
            self.nav.tag_configure("cat", font=(FONT, 10, "bold"))
            self.nav.bind("<<TreeviewSelect>>", self._on_nav_select)

            main = ttk.Frame(body, style="TFrame", padding=(16, 12))
            main.pack(side="left", fill="both", expand=True)

            head = ttk.Frame(main, style="TFrame")
            head.pack(fill="x")
            self.title_lbl = ttk.Label(head, text="Welcome", style="Header.TLabel")
            self.title_lbl.pack(anchor="w")
            self.desc_lbl = ttk.Label(head, text="", style="Sub.TLabel",
                                      wraplength=680, justify="left")
            self.desc_lbl.pack(anchor="w", pady=(2, 8))
            ttk.Separator(main).pack(fill="x")

            self.container = ttk.Frame(main, style="TFrame")
            self.container.pack(fill="both", expand=True, pady=(10, 8))

            bar = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 6))
            bar.pack(fill="x", side="bottom")
            self.status_lbl = ttk.Label(bar, text="Ready", style="Status.TLabel",
                                        width=14, anchor="w")
            self.status_lbl.pack(side="left")
            self.result_lbl = ttk.Label(bar, text="", style="Status.TLabel",
                                        anchor="w", wraplength=720, justify="left")
            self.result_lbl.pack(side="left", fill="x", expand=True, padx=8)

        def _select_first_tool(self):
            for iid in self._nav_ids:
                self.nav.selection_set(iid)
                self.nav.see(iid)
                break

        def _select_tool(self, tool_id):
            for iid, tid in self._nav_ids.items():
                if tid == tool_id:
                    self.nav.selection_set(iid)
                    self.nav.see(iid)
                    return

        def _on_nav_select(self, _e=None):
            sel = self.nav.selection()
            if not sel:
                return
            tid = self._nav_ids.get(sel[0])
            if tid:
                self._show_tool(tid)

        def _show_tool(self, tool_id):
            if self._current is not None:
                self._current.pack_forget()
            panel = self._panels.get(tool_id)
            if panel is None:
                panel = ttk.Frame(self.container, style="TFrame")
                builder = getattr(self, "_panel_" + tool_id, None)
                if builder:
                    builder(panel)
                else:
                    ttk.Label(panel, text="Not implemented.").pack()
                self._panels[tool_id] = panel
                self._apply_theme()
            panel.pack(fill="both", expand=True)
            self._current = panel
            title, desc = self._tool_meta(tool_id)
            self.title_lbl.configure(text=title)
            self.desc_lbl.configure(text=desc)
            self._clear_result()
            if tool_id in ("transcribe", "dictate"):
                self._refresh_model_combos()

        def _tool_meta(self, tool_id):
            for _cat, tools in TOOL_TREE:
                for tid, label in tools:
                    if tid == tool_id:
                        return label, TOOL_DESCRIPTIONS.get(tid, "")
            return tool_id, ""

        # ---- background operation runner
        def _bg(self, work, on_ok, button=None, busy="Working…"):
            """Run ``work()`` off the UI thread; call ``on_ok(result)`` back on it.

            Errors are shown inline (VoiceTypeError message, or a generic note),
            never as a traceback.  Refuses a second op while one is in flight.
            """
            if self._busy:
                self._show_error("Please wait — an operation is already running.")
                return
            self._busy = True
            if button is not None:
                try:
                    button.state(["disabled"])
                except Exception:
                    pass
            self._set_status(busy, kind="working")
            self._clear_result(keep_status=True)

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
                    self._set_status("error", kind="err")
                    self._show_error(err)
                    return
                self._set_status("done", kind="ok")
                try:
                    on_ok(res)
                except Exception as ex:
                    self._show_error(f"Post-processing error: {ex}")

            threading.Thread(target=run, daemon=True).start()

        # ---- result bar helpers
        def _set_status(self, text, kind="idle"):
            p = self._pal()
            color = {"working": p["primary"], "ok": p["ok"], "err": p["err"]}.get(
                kind, p["muted"])
            self.status_lbl.configure(text=text, foreground=color)

        def _clear_result(self, keep_status=False):
            self.result_lbl.configure(text="")
            if not keep_status:
                self._set_status("Ready")

        def _show_error(self, message):
            # keep the inline bar to a single line; models/guidance can be long
            first = str(message).splitlines()[0] if message else "error"
            self.result_lbl.configure(text="✕ " + first,
                                      foreground=self._pal()["err"])
            self._set_status("error", kind="err")

        def _show_ok(self, message):
            self.result_lbl.configure(text="✓ " + message,
                                      foreground=self._pal()["ok"])
            self._set_status("done", kind="ok")

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
        # Panel: Transcribe
        # =================================================================
        def _panel_transcribe(self, panel):
            self._tr_input = tk.StringVar()
            self._tr_model = tk.StringVar()
            self._tr_words = tk.BooleanVar(value=False)

            row = ttk.Frame(panel, style="TFrame")
            row.pack(fill="x", pady=(0, 6))
            ttk.Label(row, text="Audio file", width=12, anchor="w").pack(side="left")
            ttk.Entry(row, textvariable=self._tr_input).pack(
                side="left", fill="x", expand=True, padx=(0, 6))
            ttk.Button(row, text="Browse…", width=10,
                       command=self._tr_browse).pack(side="left")

            row2 = ttk.Frame(panel, style="TFrame")
            row2.pack(fill="x", pady=(0, 6))
            ttk.Label(row2, text="Model", width=12, anchor="w").pack(side="left")
            self._tr_model_combo = ttk.Combobox(
                row2, textvariable=self._tr_model, state="readonly", width=34)
            self._tr_model_combo.pack(side="left", padx=(0, 6))
            ttk.Checkbutton(row2, text="Word timestamps",
                            variable=self._tr_words).pack(side="left", padx=6)
            self._tr_run = ttk.Button(row2, text="Transcribe",
                                      style="Accent.TButton", command=self._tr_run)
            self._tr_run.pack(side="right")

            box = ttk.Frame(panel, style="TFrame")
            box.pack(fill="both", expand=True)
            self._tr_text = tk.Text(box, wrap="word", height=14, undo=True)
            sb = ttk.Scrollbar(box, orient="vertical", command=self._tr_text.yview)
            self._tr_text.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._tr_text.pack(side="left", fill="both", expand=True)
            self.track(self._tr_text, "text")

            saverow = ttk.Frame(panel, style="TFrame")
            saverow.pack(fill="x", pady=(8, 0))
            ttk.Button(saverow, text="Save as TXT…",
                       command=lambda: self._tr_save("txt")).pack(side="left")
            ttk.Button(saverow, text="Save as SRT…",
                       command=lambda: self._tr_save("srt")).pack(side="left", padx=6)
            ttk.Button(saverow, text="Save as VTT…",
                       command=lambda: self._tr_save("vtt")).pack(side="left")
            ttk.Button(saverow, text="Copy", command=self._tr_copy).pack(side="right")

        def _tr_browse(self):
            p = filedialog.askopenfilename(title="Choose audio", filetypes=AUDIO_TYPES)
            if p:
                self._tr_input.set(p)

        def _tr_run(self):
            path = self._tr_input.get().strip()
            model = self._tr_model.get().strip()
            words = bool(self._tr_words.get())
            if not path:
                self._show_error("Choose an audio file first.")
                return
            if model not in self._installed_models():
                self._show_error("No model installed — open the Models tab to "
                                 "download one.")
                return

            def work():
                model_dir = models.resolve_model_dir(model)
                return transcribe.transcribe_file(path, model_dir, words=words)

            def done(result):
                self._last_result = result
                self._tr_text.delete("1.0", "end")
                self._tr_text.insert("1.0", result.text or "(no speech detected)")
                guiconfig.set_last_model(model)
                self._show_ok(f"Transcribed {os.path.basename(path)} "
                              f"({len(result.segments)} segments).")

            self._bg(work, done, button=self._tr_run, busy="Transcribing…")

        def _tr_save(self, kind):
            if self._last_result is None:
                self._show_error("Nothing to save yet — run Transcribe first.")
                return
            ext = {"txt": ".txt", "srt": ".srt", "vtt": ".vtt"}[kind]
            p = filedialog.asksaveasfilename(
                title=f"Save as {kind.upper()}", defaultextension=ext,
                filetypes=[(f"{kind.upper()} files", "*" + ext), ("All files", "*.*")])
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
                self._show_ok(f"Saved {os.path.basename(p)}")
            except Exception as ex:
                self._show_error(f"Could not save: {ex}")

        def _tr_copy(self):
            text = self._tr_text.get("1.0", "end").strip()
            if text:
                self.clipboard_clear()
                self.clipboard_append(text)
                self._show_ok("Copied transcript to clipboard.")

        # =================================================================
        # Panel: Dictate
        # =================================================================
        def _panel_dictate(self, panel):
            self._dc_model = tk.StringVar()
            self._dc_device = tk.StringVar()
            self._dc_type = tk.BooleanVar(value=False)
            self._dc_devices = []  # list of (label, index)

            row = ttk.Frame(panel, style="TFrame")
            row.pack(fill="x", pady=(0, 6))
            ttk.Label(row, text="Model", width=12, anchor="w").pack(side="left")
            self._dc_model_combo = ttk.Combobox(
                row, textvariable=self._dc_model, state="readonly", width=34)
            self._dc_model_combo.pack(side="left", padx=(0, 6))

            row2 = ttk.Frame(panel, style="TFrame")
            row2.pack(fill="x", pady=(0, 6))
            ttk.Label(row2, text="Microphone", width=12, anchor="w").pack(side="left")
            self._dc_device_combo = ttk.Combobox(
                row2, textvariable=self._dc_device, state="readonly", width=34)
            self._dc_device_combo.pack(side="left", padx=(0, 6))
            ttk.Button(row2, text="Refresh", width=8,
                       command=self._dc_refresh_devices).pack(side="left")

            row3 = ttk.Frame(panel, style="TFrame")
            row3.pack(fill="x", pady=(0, 6))
            ttk.Checkbutton(
                row3, variable=self._dc_type,
                text="Type into the focused window (Windows only)").pack(side="left")
            self._dc_start = ttk.Button(row3, text="Start", style="Accent.TButton",
                                        command=self._dc_start)
            self._dc_start.pack(side="right")
            self._dc_stop = ttk.Button(row3, text="Stop", command=self._dc_stop,
                                       state="disabled")
            self._dc_stop.pack(side="right", padx=(0, 6))

            box = ttk.Frame(panel, style="TFrame")
            box.pack(fill="both", expand=True)
            self._dc_text = tk.Text(box, wrap="word", height=12)
            sb = ttk.Scrollbar(box, orient="vertical", command=self._dc_text.yview)
            self._dc_text.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._dc_text.pack(side="left", fill="both", expand=True)
            self.track(self._dc_text, "text")

            self._dc_partial = ttk.Label(panel, style="Sub.TLabel", anchor="w",
                                         wraplength=720, text="")
            self._dc_partial.pack(fill="x", pady=(4, 0))

            bottom = ttk.Frame(panel, style="TFrame")
            bottom.pack(fill="x", pady=(6, 0))
            ttk.Button(bottom, text="Copy", command=self._dc_copy).pack(side="right")
            ttk.Button(bottom, text="Clear",
                       command=lambda: self._dc_text.delete("1.0", "end")).pack(
                side="right", padx=6)

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
                                    for d in devs if d["index"] == i and d["default"]),
                                   labels[0])
                    self._dc_device.set(default)
            except VoiceTypeError as ex:
                self._dc_devices = []
                self._dc_device_combo.configure(values=["(no audio backend)"])
                self._dc_device.set("(no audio backend)")
                self._show_error(str(ex))

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
                self._show_error("No model installed — open the Models tab to "
                                 "download one.")
                return
            device = self._dc_selected_device()
            type_out = bool(self._dc_type.get())

            self._dictation_stop = threading.Event()
            stop = self._dictation_stop
            self._dc_start.configure(state="disabled")
            self._dc_stop.configure(state="normal")
            self._set_status("Listening…", kind="working")
            guiconfig.set_last_model(model)

            def worker():
                try:
                    model_dir = models.resolve_model_dir(model)
                    for event in dictate.dictate(model_dir, device=device,
                                                 stop_event=stop):
                        self.after(0, lambda e=event: self._dc_event(e, type_out))
                except VoiceTypeError as ex:
                    self.after(0, lambda: self._dc_finished(str(ex)))
                    return
                except Exception as ex:  # pragma: no cover - defensive
                    self.after(0, lambda: self._dc_finished(f"Unexpected error: {ex}"))
                    return
                self.after(0, lambda: self._dc_finished(None))

            self._dictation_thread = threading.Thread(target=worker, daemon=True)
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
                        self._show_error(str(ex))

        def _dc_stop(self):
            if self._dictation_stop is not None:
                self._dictation_stop.set()
            self._dc_stop.configure(state="disabled")
            self._set_status("Stopping…", kind="working")

        def _dc_finished(self, err):
            self._dc_partial.configure(text="")
            self._dc_start.configure(state="normal")
            self._dc_stop.configure(state="disabled")
            if err:
                self._show_error(err)
            else:
                self._show_ok("Dictation stopped.")

        def _dc_copy(self):
            text = self._dc_text.get("1.0", "end").strip()
            if text:
                self.clipboard_clear()
                self.clipboard_append(text)
                self._show_ok("Copied dictation to clipboard.")

        # =================================================================
        # Panel: Models
        # =================================================================
        def _panel_models(self, panel):
            top = ttk.Frame(panel, style="TFrame")
            top.pack(fill="both", expand=True)

            cols = ("language", "size", "status")
            self._md_tree = ttk.Treeview(top, columns=cols, show="tree headings",
                                         selectmode="browse", height=12)
            self._md_tree.heading("#0", text="Model")
            self._md_tree.heading("language", text="Language")
            self._md_tree.heading("size", text="Size")
            self._md_tree.heading("status", text="Status")
            self._md_tree.column("#0", width=280)
            self._md_tree.column("language", width=130)
            self._md_tree.column("size", width=90, anchor="center")
            self._md_tree.column("status", width=100, anchor="center")
            sb = ttk.Scrollbar(top, orient="vertical", command=self._md_tree.yview)
            self._md_tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self._md_tree.pack(side="left", fill="both", expand=True)

            ctrl = ttk.Frame(panel, style="TFrame")
            ctrl.pack(fill="x", pady=(8, 0))
            self._md_install = ttk.Button(ctrl, text="Install selected",
                                          style="Accent.TButton",
                                          command=self._md_install_selected)
            self._md_install.pack(side="left")
            ttk.Button(ctrl, text="Refresh",
                       command=self._md_refresh).pack(side="left", padx=6)
            ttk.Button(ctrl, text="Open models folder",
                       command=lambda: open_in_file_manager(models.models_dir())
                       ).pack(side="left")
            self._md_progress = ttk.Progressbar(ctrl, mode="determinate",
                                                 length=220, maximum=100)
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
                self._show_error("Select a model to install.")
                return
            name = sel[0]
            if models.is_installed(name):
                self._show_ok(f"{name} is already installed.")
                return

            self._md_install.configure(state="disabled")
            self._md_progress.configure(value=0)
            self._set_status("Downloading…", kind="working")
            self._busy = True

            def progress(done, total):
                pct = int(done * 100 / total) if total else 0
                self.after(0, lambda: self._md_progress.configure(value=pct))

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
            self._md_install.configure(state="normal")
            self._md_progress.configure(value=0)
            if err:
                self._show_error(err)
            else:
                self._show_ok(f"Installed {name}.")
            self._md_refresh()

        # ---- about / close
        def _about(self):
            win = tk.Toplevel(self)
            win.title("About VoiceType")
            win.configure(bg=self._pal()["bg"])
            win.resizable(False, False)
            frm = ttk.Frame(win, style="TFrame", padding=18)
            frm.pack(fill="both", expand=True)
            ttk.Label(frm, text="VoiceType", style="Header.TLabel").pack(anchor="w")
            ttk.Label(frm, text=f"Version {APP_VERSION}",
                      style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
            ttk.Label(frm, style="TLabel", justify="left", wraplength=380,
                      text="A fast, fully-offline speech-to-text & dictation app "
                           "built on the permissively-licensed Vosk engine.\n\n"
                           "100% AI-built, open source, published on QuickOpen.\n"
                           "Nothing is ever uploaded anywhere.").pack(anchor="w")
            ttk.Button(frm, text="Close", command=win.destroy).pack(
                anchor="e", pady=(12, 0))
            self._apply_theme()

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
    With no display (e.g. a server), it prints a friendly note and returns 0
    instead of raising.
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
