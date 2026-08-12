#!/usr/bin/env python3
r"""VoiceType entry point (built into VoiceType.exe). GUI with no args, CLI with args."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Single-instance marker: the installer's AppMutex checks this to warn the
# user to close the app before install/uninstall. Harmless off Windows.
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "QuickOpen.VoiceType")
    except Exception:
        pass



def main():
    argv = sys.argv[1:]
    if argv:
        from voicetype import __main__ as cli
        if hasattr(cli, 'main'):
            try:
                return cli.main(argv)
            except TypeError:
                sys.argv = ['voicetype', *argv]; return cli.main()
        sys.argv = ['voicetype', *argv]
        import runpy; runpy.run_module('voicetype', run_name='__main__'); return 0
    from voicetype import gui
    return gui.main() or 0


if __name__ == '__main__':
    sys.exit(main() or 0)
