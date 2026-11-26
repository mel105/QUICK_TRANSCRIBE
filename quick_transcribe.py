"""
Launcher for quick_transcribe - offline transcription of recordings with a
searchable archive. The whole tool lives in this folder: this launcher,
quick_transcribe.json and the package quick_transcribe/.

    python quick_transcribe.py [FILE ...]
    python quick_transcribe.py transcribe FILE [...]

Author: MEL
"""

import importlib
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _stop(message: str) -> None:
    """Report a start-up problem: console if there is one, otherwise a message box."""
    if sys.stdout is None or sys.executable.lower().endswith("pythonw.exe"):
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("quick_transcribe", message)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(2)
    sys.exit(message)


missing = [m for m in ("faster_whisper", "av") if importlib.util.find_spec(m) is None]
if missing:
    _stop("quick_transcribe cannot start: this Python has no " + ", ".join(missing) + ".\n\n"
          "Python in use: " + sys.executable + "\n\n"
          "Activate your environment first, or install the packages:\n"
          "    \"" + sys.executable + "\" -m pip install faster-whisper \"av==16.0.1\"")

try:
    import av  # noqa: E402
    major = int(str(av.__version__).split(".")[0])
    if major >= 17:
        _stop(f"quick_transcribe: PyAV {av.__version__} does not work with faster-whisper "
              "(open() got an unexpected keyword argument 'metadata_errors').\n\n"
              "Fix:\n    \"" + sys.executable + "\" -m pip install \"av==16.0.1\"")
except ValueError:
    pass

pkg = importlib.import_module("quick_transcribe")
if not hasattr(pkg, "__path__"):
    _stop("quick_transcribe: the package folder quick_transcribe/ is missing next to the launcher.")

from quick_transcribe.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
