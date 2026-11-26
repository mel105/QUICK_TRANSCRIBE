"""
Local HTTP server of quick_transcribe (standard library only).

The page in the browser talks to this process over JSON. Audio, transcripts and the
database stay on this computer; the server listens on 127.0.0.1 by default.

Author: MEL
"""

from __future__ import annotations

import glob
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import APP_NAME, __version__
from . import db as dbm
from . import log
from . import settings as st
from .engine import AUDIO_EXT, Engine

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
KEEP_DB_BACKUPS = 20


class App:
    def __init__(self, cfg: dict, model_factory=None):
        self.cfg = cfg
        self.data_dir = st.data_dir(cfg)
        self.settings = st.UserSettings(self.data_dir)
        self.archive = dbm.Archive(dbm.default_db_path(self.data_dir))
        self.engine = Engine(self.archive, self.settings, self.data_dir, model_factory=model_factory)
        self.httpd: Optional[ThreadingHTTPServer] = None

    def open_paths(self, paths, force: bool = False) -> list:
        jobs, skipped = [], []
        for p in paths:
            if os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    fp = os.path.join(p, f)
                    if os.path.isfile(fp) and f.lower().endswith(AUDIO_EXT):
                        jobs.append(self.engine.submit(fp, force=force).public())
            elif os.path.isfile(p):
                jobs.append(self.engine.submit(p, force=force).public())
            else:
                skipped.append(p)
        if skipped:
            raise FileNotFoundError("Not found: " + ", ".join(skipped))
        return jobs

    def backup(self, target_dir: str = "") -> dict:
        target_dir = (target_dir or self.settings.get("backup_dir") or "").strip()
        if not target_dir:
            raise ValueError("Set the backup folder in Settings first.")
        root = os.path.join(os.path.expanduser(target_dir), "quick_transcribe_backup")
        os.makedirs(os.path.join(root, "audio"), exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        db_target = os.path.join(root, f"transcripts_{stamp}.db")
        self.archive.backup_to(db_target)
        copied = 0
        for f in glob.glob(os.path.join(self.data_dir, "audio", "*.opus")):
            dst = os.path.join(root, "audio", os.path.basename(f))
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(f):
                shutil.copy2(f, dst)
                copied += 1
        olds = sorted(glob.glob(os.path.join(root, "transcripts_*.db")))
        for old in olds[:-KEEP_DB_BACKUPS]:
            try:
                os.remove(old)
            except OSError:
                pass
        self.settings.update({"backup_dir": target_dir})
        return {"folder": root, "database": db_target, "audio_copied": copied}


def _json_default(o):
    return str(o)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"{APP_NAME}/{__version__}"

        def log_message(self, fmt, *args):  # quiet console
            pass

        # ---------- helpers ----------
        def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, default=_json_default, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _err(self, code: int, msg: str):
            self._json({"error": msg}, code)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

        def _guard(self) -> bool:
            # state-changing requests must come from our page (custom header -> no cross-site forms)
            if self.headers.get("X-QT") != "1":
                self._err(403, "Missing X-QT header.")
                return False
            return True

        def _route(self):
            u = urllib.parse.urlparse(self.path)
            return u.path, urllib.parse.parse_qs(u.query)

        # ---------- GET ----------
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            try:
                path, qs = self._route()
                if path in ("/", "/index.html"):
                    return self._static("index.html")
                if path.startswith("/static/"):
                    return self._static(path[len("/static/"):])
                if path == "/icon.png":
                    p = os.path.join(st.tool_dir(), "quick_transcribe.png")
                    if os.path.isfile(p):
                        with open(p, "rb") as f:
                            return self._send(200, f.read(), "image/png")
                    return self._err(404, "no icon")
                if path == "/api/ping":
                    return self._json({"app": APP_NAME, "version": __version__})
                if path == "/api/state":
                    return self._json({
                        "app": APP_NAME, "version": __version__, "settings": app.settings.values,
                        "models": st.MODELS, "languages": st.LANGUAGES, "jobs": app.engine.state(),
                        "busy": app.engine.busy(), "data_dir": app.data_dir, "fts": app.archive.fts})
                if path == "/api/jobs":
                    return self._json({"jobs": app.engine.state(), "busy": app.engine.busy()})
                if path == "/api/recordings":
                    return self._json({"recordings": app.archive.list_recordings()})
                if path == "/api/search":
                    q = (qs.get("q") or [""])[0]
                    return self._json({"hits": app.archive.search(q)})
                m = re.fullmatch(r"/api/recordings/(\d+)", path)
                if m:
                    rec = app.archive.get_recording(int(m.group(1)))
                    if not rec:
                        return self._err(404, "Recording not found.")
                    after = int((qs.get("after") or ["-1"])[0])
                    rec["has_audio"] = bool(rec.get("audio_path") and os.path.isfile(rec["audio_path"]))
                    rec["source_exists"] = bool(rec.get("source_path") and os.path.isfile(rec["source_path"]))
                    return self._json({"recording": rec, "segments": app.archive.segments(rec["id"], after)})
                m = re.fullmatch(r"/api/recordings/(\d+)/export", path)
                if m:
                    return self._export(int(m.group(1)), (qs.get("fmt") or ["txt"])[0])
                m = re.fullmatch(r"/audio/(\d+)", path)
                if m:
                    return self._audio(int(m.group(1)))
                return self._err(404, "Not found.")
            except Exception as exc:  # noqa: BLE001
                log.exc(self.path)
                return self._err(500, f"{type(exc).__name__}: {exc}")

        def _static(self, rel: str):
            p = os.path.normpath(os.path.join(STATIC_DIR, rel))
            if not p.startswith(STATIC_DIR) or not os.path.isfile(p):
                return self._err(404, "Not found.")
            ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            with open(p, "rb") as f:
                self._send(200, f.read(), ctype)

        def _export(self, rec_id: int, fmt: str):
            rec = app.archive.get_recording(rec_id)
            if not rec:
                return self._err(404, "Recording not found.")
            fmt = fmt if fmt in ("txt", "srt", "md", "plain") else "txt"
            text = dbm.export_text(rec, app.archive.segments(rec_id), fmt)
            ext = "txt" if fmt == "plain" else fmt
            safe = re.sub(r"[^\w\-. ]+", "_", rec["name"]).strip() or f"recording_{rec_id}"
            fname = urllib.parse.quote(f"{safe}.{ext}")
            self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8",
                       {"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})

        def _audio(self, rec_id: int):
            rec = app.archive.get_recording(rec_id)
            p = rec.get("audio_path") if rec else None
            if not p or not os.path.isfile(p):
                return self._err(404, "No archived audio for this recording.")
            size = os.path.getsize(p)
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            code = 200
            if rng:
                m = re.match(r"bytes=(\d*)-(\d*)", rng)
                if m:
                    if m.group(1):
                        start = int(m.group(1))
                        if m.group(2):
                            end = min(int(m.group(2)), size - 1)
                    elif m.group(2):  # suffix range
                        start = max(0, size - int(m.group(2)))
                    code = 206
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(code)
            self.send_header("Content-Type", "audio/ogg")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(p, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        # ---------- POST / PATCH / PUT / DELETE ----------
        def do_POST(self):
            if not self._guard():
                return
            try:
                path, qs = self._route()
                if path == "/api/upload":
                    return self._upload(qs)
                body = self._body()
                if path == "/api/open":
                    jobs = app.open_paths(body.get("paths") or [], bool(body.get("force")))
                    return self._json({"jobs": jobs})
                m = re.fullmatch(r"/api/jobs/(\w+)/cancel", path)
                if m:
                    return self._json({"ok": app.engine.cancel(m.group(1))})
                m = re.fullmatch(r"/api/recordings/(\d+)/redo", path)
                if m:
                    job = app.engine.redo(int(m.group(1)), body.get("model") or None,
                                          body.get("language") if "language" in body else None)
                    return self._json({"job": job.public()})
                m = re.fullmatch(r"/api/recordings/(\d+)/replace", path)
                if m:
                    n = app.archive.replace_all(int(m.group(1)), body.get("find", ""), body.get("replace", ""),
                                                bool(body.get("whole_word", True)))
                    return self._json({"replaced": n})
                if path == "/api/backup":
                    return self._json(app.backup(body.get("folder", "")))
                if path == "/api/quit":
                    self._json({"ok": True})
                    threading.Thread(target=app.httpd.shutdown, daemon=True).start()
                    return
                return self._err(404, "Not found.")
            except (ValueError, KeyError, FileNotFoundError) as exc:
                return self._err(400, str(exc))
            except Exception as exc:  # noqa: BLE001
                log.exc(self.path)
                return self._err(500, f"{type(exc).__name__}: {exc}")

        def _upload(self, qs):
            name = os.path.basename((qs.get("name") or ["recording.m4a"])[0]) or "recording.m4a"
            base, ext = os.path.splitext(name)
            if ext.lower() not in AUDIO_EXT:
                return self._err(400, f"Unsupported file type: {ext or '(none)'}")
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return self._err(400, "Empty upload.")
            dst = os.path.join(app.data_dir, "inbox", f"{int(time.time()*1000)}_{os.getpid()}{ext.lower()}")
            left = n
            with open(dst, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            if left:
                os.remove(dst)
                return self._err(400, "Upload interrupted.")
            recorded = None
            lm = (qs.get("lastModified") or [""])[0]
            if lm.isdigit():
                recorded = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(lm) / 1000))
            force = (qs.get("force") or ["0"])[0] == "1"
            job = app.engine.submit(dst, name=base, recorded_at=recorded, delete_source=True, force=force)
            return self._json({"job": job.public()})

        def do_PATCH(self):
            if not self._guard():
                return
            try:
                path, _ = self._route()
                body = self._body()
                m = re.fullmatch(r"/api/segments/(\d+)", path)
                if m:
                    return self._json({"segment": app.archive.edit_segment(int(m.group(1)), str(body.get("text", "")).strip())})
                m = re.fullmatch(r"/api/recordings/(\d+)", path)
                if m:
                    fields = {k: str(v).strip() for k, v in body.items() if k in ("name", "note")}
                    if "name" in fields and not fields["name"]:
                        return self._err(400, "Name cannot be empty.")
                    app.archive.update_recording(int(m.group(1)), **fields)
                    return self._json({"recording": app.archive.get_recording(int(m.group(1)))})
                return self._err(404, "Not found.")
            except KeyError:
                return self._err(404, "Not found.")
            except Exception as exc:  # noqa: BLE001
                log.exc(self.path)
                return self._err(500, f"{type(exc).__name__}: {exc}")

        def do_PUT(self):
            if not self._guard():
                return
            try:
                path, _ = self._route()
                if path == "/api/settings":
                    return self._json({"settings": app.settings.update(self._body())})
                return self._err(404, "Not found.")
            except ValueError as exc:
                return self._err(400, str(exc))

        def do_DELETE(self):
            if not self._guard():
                return
            path, _ = self._route()
            m = re.fullmatch(r"/api/recordings/(\d+)", path)
            if not m:
                return self._err(404, "Not found.")
            rec_id = int(m.group(1))
            if app.engine.current and app.engine.current.rec_id == rec_id:
                return self._err(409, "This recording is being transcribed. Cancel the job first.")
            rec = app.archive.delete_recording(rec_id)
            if rec and rec.get("audio_path") and os.path.isfile(rec["audio_path"]):
                try:
                    os.remove(rec["audio_path"])
                except OSError:
                    pass
            return self._json({"ok": bool(rec)})

    return Handler


def serve(app: App, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    app.httpd = httpd
    return httpd
