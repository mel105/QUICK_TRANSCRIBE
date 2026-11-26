"""
Command line of quick_transcribe.

    python quick_transcribe.py                       open the app in the browser
    python quick_transcribe.py FILE [FILE ...]       open the app and transcribe these files
    python quick_transcribe.py transcribe FILE [...] transcribe in the console, no browser
    python quick_transcribe.py backup [FOLDER]       back up the database and archived audio
    python quick_transcribe.py info                  data folder, settings, number of recordings

Options: --port 8775, --host 0.0.0.0, --no-browser; transcribe: --model, --lang, --force, --txt

Author: MEL
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import webbrowser
from typing import List

from . import APP_NAME, __version__

COMMANDS = ("serve", "transcribe", "backup", "info")


def _say(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:  # pythonw has no console
        pass


def _running(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=0.6) as r:
            return json.loads(r.read().decode()).get("app") == APP_NAME
    except Exception:
        return False


def _post(host: str, port: int, path: str, payload: dict) -> dict:
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "X-QT": "1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def cmd_serve(files: List[str], args) -> int:
    from . import server, settings
    cfg = settings.load_config()
    host = args.host or cfg["server"]["host"]
    port = args.port or int(cfg["server"]["port"])
    local = "127.0.0.1" if host in ("0.0.0.0", "") else host
    url = f"http://{local}:{port}/"
    files = [os.path.abspath(f) for f in files]
    open_browser = cfg["server"].get("open_browser", True) and not args.no_browser

    if _running(local, port):
        if files:
            try:
                _post(local, port, "/api/open", {"paths": files})
            except Exception as exc:  # noqa: BLE001
                _say(f"Could not pass the files to the running app: {exc}")
        _say(f"{APP_NAME} is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return 0

    app = server.App(cfg)
    try:
        httpd = server.serve(app, host, port)
    except OSError as exc:
        _say(f"ERROR: cannot start the server on {host}:{port} ({exc}). Use --port or change quick_transcribe.json.")
        return 2
    if files:
        try:
            app.open_paths(files)
        except FileNotFoundError as exc:
            _say(str(exc))
    _say(f"{APP_NAME} {__version__} running at {url}  (data: {app.data_dir})")
    _say("Stop: Quit in the page or Ctrl+C here.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        app.archive.close()
    return 0


def cmd_transcribe(args) -> int:
    from . import db as dbm
    from . import settings
    from .server import App
    cfg = settings.load_config()
    app = App(cfg)
    lang = args.lang if args.lang is not None else None
    jobs = [app.engine.submit(os.path.abspath(f), force=args.force, model=args.model, language=lang)
            for f in args.files]
    shown = {j.id: 0 for j in jobs}
    while any(j.status in ("queued", "archiving", "loading", "running") for j in jobs):
        for j in jobs:
            if j.rec_id and j.status == "running":
                segs = app.archive.segments(j.rec_id, shown[j.id] - 1)
                for s in segs:
                    _say(f"[{dbm.fmt_time(s['start'])}] {s['text']}")
                    shown[j.id] = s["idx"] + 1
        time.sleep(0.5)
    rc = 0
    for j in jobs:
        if j.rec_id and j.status == "done":
            for s in app.archive.segments(j.rec_id, shown[j.id] - 1):
                _say(f"[{dbm.fmt_time(s['start'])}] {s['text']}")
        _say(f"{j.name}: {j.status} - {j.message}")
        if j.status == "error":
            rc = 1
        if args.txt and j.rec_id and j.status in ("done", "duplicate"):
            rec = app.archive.get_recording(j.rec_id)
            out = os.path.splitext(os.path.abspath(j.source))[0] + ".txt"
            with open(out, "w", encoding="utf-8") as f:
                f.write(dbm.export_text(rec, app.archive.segments(j.rec_id), "txt"))
            _say(f"  -> {out}")
    app.archive.close()
    return rc


def cmd_backup(args) -> int:
    from . import settings
    from .server import App
    app = App(settings.load_config())
    try:
        res = app.backup(args.folder or "")
    except ValueError as exc:
        _say(str(exc) + "  (python quick_transcribe.py backup FOLDER)")
        return 1
    _say(f"Database: {res['database']}\nAudio files copied: {res['audio_copied']}")
    return 0


def cmd_info(_args) -> int:
    from . import db as dbm
    from . import settings
    cfg = settings.load_config()
    d = settings.data_dir(cfg)
    us = settings.UserSettings(d)
    a = dbm.Archive(dbm.default_db_path(d))
    recs = a.list_recordings()
    _say(f"{APP_NAME} {__version__}\nData folder: {d}\nFull-text search: {'FTS5' if a.fts else 'LIKE (slower)'}")
    _say(f"Recordings: {len(recs)} ({sum(1 for r in recs if r['status'] == 'done')} done)")
    _say("Settings: " + json.dumps(us.values, ensure_ascii=False))
    a.close()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv and argv[0] in COMMANDS else "serve"
    if argv and argv[0] in COMMANDS:
        argv = argv[1:]
    p = argparse.ArgumentParser(prog=APP_NAME)
    if cmd == "serve":
        p.add_argument("files", nargs="*")
        p.add_argument("--host", default="")
        p.add_argument("--port", type=int, default=0)
        p.add_argument("--no-browser", action="store_true")
        a = p.parse_args(argv)
        return cmd_serve(a.files, a)
    if cmd == "transcribe":
        p.add_argument("files", nargs="+")
        p.add_argument("--model", default=None)
        p.add_argument("--lang", default=None, help="en, cs, sk ... ; empty string = detect")
        p.add_argument("--force", action="store_true", help="transcribe even if already in the archive")
        p.add_argument("--txt", action="store_true", help="also write FILE.txt next to the source")
        return cmd_transcribe(p.parse_args(argv))
    if cmd == "backup":
        p.add_argument("folder", nargs="?", default="")
        return cmd_backup(p.parse_args(argv))
    return cmd_info(p.parse_args(argv))
