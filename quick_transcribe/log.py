"""
Error log of quick_transcribe: <data_dir>/quick_transcribe.log.

Under pythonw there is no console (sys.stderr is None), so tracebacks go to this
file; with a console they are printed as well.

Author: MEL
"""

from __future__ import annotations

import os
import sys
import time
import traceback

_path = ""
MAX_BYTES = 1_000_000


def set_folder(folder: str) -> None:
    global _path
    _path = os.path.join(folder, "quick_transcribe.log")


def path() -> str:
    return _path


def exc(context: str = "") -> None:
    text = f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {context}\n{traceback.format_exc()}"
    if sys.stderr is not None:
        try:
            sys.stderr.write(text)
        except Exception:  # noqa: BLE001
            pass
    if _path:
        try:
            if os.path.exists(_path) and os.path.getsize(_path) > MAX_BYTES:
                os.replace(_path, _path + ".1")
            with open(_path, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass
