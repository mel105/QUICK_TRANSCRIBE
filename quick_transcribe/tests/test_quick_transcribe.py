"""
Tests of quick_transcribe without downloading a model (a fake model is injected).

    python -m unittest discover -s quick_transcribe/tests -v      (from the tool folder)

Author: MEL
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from quick_transcribe import db as dbm  # noqa: E402
from quick_transcribe import engine as eng  # noqa: E402
from quick_transcribe import server, settings  # noqa: E402

LINES = ["Welcome to the Task 6.2 kick-off.", "We discuss the ASTP demonstrators.",
         "EGNOS v3 data are not available yet.", "Next meeting in December."]


class FakeModel:
    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = []

    def transcribe(self, fh, **kw):
        fh.read(16)  # must be a readable file object
        self.calls.append(kw)

        def gen():
            for i, t in enumerate(LINES):
                time.sleep(self.delay)
                yield SimpleNamespace(start=i * 2.0, end=i * 2.0 + 1.8, text=" " + t)
        return gen(), SimpleNamespace(duration=8.0, language="en")


def make_audio(path: str, seconds: float = 3.0) -> None:
    """Write a short sine tone as m4a with PyAV."""
    import av
    import numpy as np
    out = av.open(path, mode="w")
    st = out.add_stream("aac", rate=44100)
    st.layout = "mono"
    n = int(44100 * seconds)
    sig = (0.2 * np.sin(2 * np.pi * 440 * np.arange(n) / 44100)).astype(np.float32)
    for k in range(0, n, 1024):
        chunk = sig[k:k + 1024].reshape(1, -1)
        fr = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="mono")
        fr.sample_rate = 44100
        for p in st.encode(fr):
            out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()


def wait(cond, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qt_test_")
        self.cfg = {"server": {"host": "127.0.0.1", "port": 0, "open_browser": False},
                    "data_dir": os.path.join(self.tmp, "data")}
        self.src = os.path.join(self.tmp, "Mlynářská porada.m4a")  # diacritics on purpose
        make_audio(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestArchive(Base):
    def test_segments_edit_search_export(self):
        a = dbm.Archive(os.path.join(self.tmp, "t.db"))
        rid = a.add_recording(name="Kick-off", status="done", duration=8.0)
        for i, t in enumerate(LINES):
            a.add_segment(rid, i, i * 2.0, i * 2.0 + 1.8, t)
        self.assertEqual(len(a.segments(rid)), 4)
        self.assertEqual(len(a.segments(rid, after_idx=1)), 2)
        hits = a.search("egnos")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["idx"], 2)
        self.assertEqual(len(a.search("demonstr")), 1)  # prefix search
        seg = a.segments(rid)[1]
        e = a.edit_segment(seg["id"], "We discuss the AZD demonstrators.")
        self.assertEqual(e["edited"], 1)
        self.assertEqual(e["original_text"], LINES[1])
        self.assertEqual(len(a.search("AZD")), 1)
        self.assertEqual(len(a.search("ASTP")), 0)  # index follows the edit
        self.assertEqual(a.edit_segment(seg["id"], LINES[1])["edited"], 0)
        self.assertEqual(a.replace_all(rid, "december", "January"), 1)
        rec = a.get_recording(rid)
        txt = dbm.export_text(rec, a.segments(rid), "txt")
        self.assertIn("[00:00:06] Next meeting in January.", txt)
        srt = dbm.export_text(rec, a.segments(rid), "srt")
        self.assertIn("00:00:02,000 --> 00:00:03,800", srt)
        self.assertIn("# Kick-off", dbm.export_text(rec, a.segments(rid), "md"))
        bk = os.path.join(self.tmp, "bk.db")
        a.backup_to(bk)
        self.assertEqual(len(dbm.Archive(bk).segments(rid)), 4)
        a.delete_recording(rid)
        self.assertEqual(a.search("egnos"), [])

    def test_interrupted_jobs_marked(self):
        p = os.path.join(self.tmp, "t.db")
        a = dbm.Archive(p)
        rid = a.add_recording(name="x", status="running")
        a.close()
        self.assertEqual(dbm.Archive(p).get_recording(rid)["status"], "error")

    def test_fmt(self):
        self.assertEqual(dbm.fmt_time(3725.9), "01:02:05")
        self.assertEqual(dbm.fmt_srt(1.9996), "00:00:02,000")


class TestEngine(Base):
    def _engine(self, model):
        d = settings.data_dir(self.cfg)
        us = settings.UserSettings(d)
        a = dbm.Archive(dbm.default_db_path(d))
        return eng.Engine(a, us, d, model_factory=lambda *k: model), a, us

    def test_full_job_archive_duplicate_redo(self):
        fm = FakeModel()
        e, a, us = self._engine(fm)
        us.update({"glossary": "ASTP\nEGNOS, DFMC"})
        job = e.submit(self.src)
        self.assertTrue(wait(lambda: job.status == "done"), job.message)
        rec = a.get_recording(job.rec_id)
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["name"], "Mlynářská porada")
        self.assertTrue(os.path.isfile(rec["audio_path"]))
        self.assertLess(os.path.getsize(rec["audio_path"]), os.path.getsize(self.src) * 3)
        self.assertEqual([s["text"] for s in a.segments(job.rec_id)], LINES)
        self.assertEqual(fm.calls[0]["initial_prompt"], "Glossary: ASTP, EGNOS, DFMC.")
        self.assertEqual(fm.calls[0]["language"], "en")
        # same file again -> duplicate, no new recording
        dup = e.submit(self.src)
        self.assertTrue(wait(lambda: dup.status == "duplicate"))
        self.assertEqual(dup.rec_id, job.rec_id)
        self.assertEqual(len(a.list_recordings()), 1)
        # redo from archived audio after the source disappears
        os.remove(self.src)
        a.update_recording(job.rec_id, source_path=None)
        r = e.redo(job.rec_id, model="tiny", language="")
        self.assertTrue(wait(lambda: r.status == "done"), r.message)
        rec = a.get_recording(job.rec_id)
        self.assertEqual(rec["model"], "tiny")
        self.assertEqual(rec["language"], "en")  # detected
        self.assertIsNone(fm.calls[-1]["language"])
        self.assertEqual(len(a.segments(job.rec_id)), 4)

    def test_cancel(self):
        e, a, _ = self._engine(FakeModel(delay=0.4))
        job = e.submit(self.src)
        self.assertTrue(wait(lambda: job.status == "running"))
        e.cancel(job.id)
        self.assertTrue(wait(lambda: job.status == "cancelled"))
        self.assertEqual(a.get_recording(job.rec_id)["status"], "cancelled")

    def test_error_is_reported(self):
        def boom(*_):
            raise RuntimeError("model broken")
        d = settings.data_dir(self.cfg)
        a = dbm.Archive(dbm.default_db_path(d))
        e = eng.Engine(a, settings.UserSettings(d), d, model_factory=boom)
        job = e.submit(self.src)
        self.assertTrue(wait(lambda: job.status == "error"))
        self.assertIn("model broken", a.get_recording(job.rec_id)["error"])

    def test_friendly_errors(self):
        self.assertIn("av==16.0.1", eng.friendly_error(TypeError("open() got an unexpected keyword argument 'metadata_errors'"), False))
        self.assertIn("not downloaded", eng.friendly_error(RuntimeError("LocalEntryNotFoundError"), True))


class TestServer(Base):
    def setUp(self):
        super().setUp()
        self.app = server.App(self.cfg, model_factory=lambda *k: FakeModel())
        self.httpd = server.serve(self.app, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.archive.close()
        super().tearDown()

    def req(self, method, path, body=None, raw=None, headers=None, guard=True):
        h = dict(headers or {})
        if guard:
            h["X-QT"] = "1"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers)

    def test_flow(self):
        code, body, _ = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"quick_transcribe", body)
        self.assertEqual(self.req("GET", "/static/app.js")[0], 200)
        self.assertEqual(self.req("GET", "/static/../server.py")[0], 404)
        self.assertEqual(self.req("POST", "/api/open", {"paths": []}, guard=False)[0], 403)

        with open(self.src, "rb") as f:
            data = f.read()
        code, body, _ = self.req("POST", "/api/upload?name=" + urllib.request.quote("Porada 1.m4a") + "&lastModified=1764000000000", raw=data)
        self.assertEqual(code, 200, body)
        job = json.loads(body)["job"]
        self.assertTrue(wait(lambda: json.loads(self.req("GET", "/api/jobs")[1])["jobs"][-1]["status"] == "done"))
        rid = json.loads(self.req("GET", "/api/jobs")[1])["jobs"][-1]["rec_id"]
        self.assertFalse(os.listdir(os.path.join(self.app.data_dir, "inbox")))  # upload copy removed

        rec = json.loads(self.req("GET", f"/api/recordings/{rid}")[1])
        self.assertTrue(rec["recording"]["has_audio"])
        self.assertEqual(len(rec["segments"]), 4)
        self.assertEqual(rec["recording"]["name"], "Porada 1")

        code, body, hdr = self.req("GET", f"/audio/{rid}", headers={"Range": "bytes=0-99"}, guard=False)
        self.assertEqual(code, 206)
        self.assertEqual(len(body), 100)
        self.assertTrue(hdr["Content-Range"].startswith("bytes 0-99/"))

        hits = json.loads(self.req("GET", "/api/search?q=egnos")[1])["hits"]
        self.assertEqual(len(hits), 1)

        seg = rec["segments"][0]
        code, body, _ = self.req("PATCH", f"/api/segments/{seg['id']}", {"text": "Welcome to the T6.2 kick-off."})
        self.assertEqual(json.loads(body)["segment"]["edited"], 1)
        self.assertEqual(self.req("PATCH", f"/api/recordings/{rid}", {"name": "Kick-off 26 Nov"})[0], 200)
        code, body, hdr = self.req("GET", f"/api/recordings/{rid}/export?fmt=md")
        self.assertIn("Kick-off 26 Nov", body.decode())
        self.assertIn("attachment", hdr["Content-Disposition"])

        code, body, _ = self.req("PUT", "/api/settings", {"model": "medium", "glossary": "ASTP"})
        self.assertEqual(json.loads(body)["settings"]["model"], "medium")
        self.assertEqual(self.req("PUT", "/api/settings", {"model": "huge"})[0], 400)

        self.assertEqual(self.req("POST", "/api/backup", {})[0], 400)  # no folder yet
        code, body, _ = self.req("POST", "/api/backup", {"folder": os.path.join(self.tmp, "bk")})
        self.assertEqual(code, 200, body)
        self.assertTrue(os.path.isfile(json.loads(body)["database"]))

        code, body, _ = self.req("POST", "/api/upload?name=notes.docx", raw=b"x")
        self.assertEqual(code, 400)

        self.assertEqual(self.req("DELETE", f"/api/recordings/{rid}")[0], 200)
        self.assertEqual(self.req("GET", f"/api/recordings/{rid}")[0], 404)


if __name__ == "__main__":
    unittest.main()
