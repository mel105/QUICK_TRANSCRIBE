"""
Configuration of quick_transcribe.

Two layers:
  * quick_transcribe.json next to the launcher - start-up options (server, data folder).
  * <data_dir>/settings.json - options changed in the app (model, language,
    glossary, backup folder ...). It lives with the data, never in the tool folder.

The data folder defaults to ~/.quick_transcribe and holds the database
(transcripts.db) and the archived audio (audio/).

Author: MEL
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict

CONFIG_DEFAULTS: Dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8774, "open_browser": True},
    "data_dir": "",
}

USER_DEFAULTS: Dict[str, Any] = {
    "model": "small",
    "language": "en",            # "" = detect automatically
    "offline": False,            # True -> never contact Hugging Face (model must be downloaded)
    "device": "cpu",             # "cpu" or "cuda"
    "compute_type": "int8",
    "beam_size": 5,
    "vad_filter": True,
    "glossary": "ASTP\nEGNOS\nDFMC\nGNSS\nERTMS\nETCS\nATO\nTRL\nKPI",
    "archive_audio": True,       # keep a compact Opus copy for playback and re-transcription
    "audio_bitrate": 24000,
    "write_txt_next_to_source": False,
    "backup_dir": "",
}

MODELS = ["tiny", "base", "small", "medium", "large-v3"]
LANGUAGES = {"en": "English", "cs": "Czech", "sk": "Slovak", "de": "German", "fr": "French", "": "Detect"}


def tool_dir() -> str:
    """Folder with the launcher and quick_transcribe.json."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str = "") -> dict:
    path = path or os.path.join(tool_dir(), "quick_transcribe.json")
    data = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    return _merge(CONFIG_DEFAULTS, data)


def data_dir(cfg: dict) -> str:
    d = (cfg.get("data_dir") or "").strip()
    d = os.path.expanduser(os.path.expandvars(d)) if d else os.path.join(os.path.expanduser("~"), ".quick_transcribe")
    os.makedirs(os.path.join(d, "audio"), exist_ok=True)
    os.makedirs(os.path.join(d, "inbox"), exist_ok=True)
    return d


class UserSettings:
    """Options edited in the app, stored as <data_dir>/settings.json."""

    def __init__(self, folder: str):
        self.path = os.path.join(folder, "settings.json")
        self.values = copy.deepcopy(USER_DEFAULTS)
        if os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.values.update(json.load(f))
            except (OSError, ValueError):
                pass

    def get(self, key: str):
        return self.values.get(key, USER_DEFAULTS.get(key))

    def update(self, changes: dict) -> dict:
        for k, v in changes.items():
            if k not in USER_DEFAULTS:
                continue
            default = USER_DEFAULTS[k]
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                v = int(v)
            else:
                v = "" if v is None else str(v)
            if k == "model" and v not in MODELS:
                raise ValueError(f"Unknown model: {v}")
            self.values[k] = v
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.values, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
        return self.values

    def glossary_terms(self) -> list:
        raw = self.get("glossary") or ""
        terms = []
        for line in raw.replace(",", "\n").splitlines():
            t = line.strip()
            if t and t not in terms:
                terms.append(t)
        return terms
