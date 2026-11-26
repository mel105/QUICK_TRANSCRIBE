"""
Background transcription: a job queue processed by one worker thread.

A job takes a source file, optionally stores a compact Opus copy of it in the
archive (for playback and later re-transcription), runs faster-whisper and writes
the segments into the database as they come, so the page shows the text live.

Everything runs locally. The model is downloaded from Hugging Face only the first
time it is used, unless the 'offline' setting is on.

Author: MEL
"""

from __future__ import annotations

import hashlib
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import db as dbm
from . import log
from .settings import UserSettings

AUDIO_EXT = (".m4a", ".mp3", ".wav", ".mp4", ".aac", ".ogg", ".opus", ".flac", ".webm", ".wma", ".mkv", ".mov")


@dataclass
class Job:
    id: str
    kind: str                     # "new" | "redo"
    name: str
    source: str
    model: str
    language: Optional[str]
    rec_id: Optional[int] = None
    recorded_at: Optional[str] = None
    delete_source: bool = False   # uploaded copies in inbox/ are removed after the job
    force: bool = False           # transcribe even when the same file is already in the archive
    status: str = "queued"        # queued, archiving, loading, running, done, duplicate, cancelled, error
    progress: float = 0.0
    message: str = ""
    started: float = 0.0
    finished: float = 0.0
    cancel: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "name": self.name, "model": self.model,
                "language": self.language or "", "rec_id": self.rec_id, "status": self.status,
                "progress": round(self.progress, 1), "message": self.message,
                "elapsed": round((self.finished or time.time()) - self.started, 1) if self.started else 0}


def sha1_of(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_opus(src: str, dst: str, bitrate: int = 24000, cancel: Optional[threading.Event] = None) -> float:
    """Transcode any audio/video file to Ogg/Opus, mono 16 kHz. Returns the duration in seconds."""
    import av  # PyAV comes with faster-whisper
    tmp = dst + ".part"
    samples = 0
    with open(src, "rb") as fh:
        inp = av.open(fh)
        try:
            out = av.open(tmp, mode="w", format="ogg")
            try:
                st = out.add_stream("libopus", rate=16000)
                st.bit_rate = int(bitrate)
                try:
                    st.layout = "mono"
                except Exception:  # noqa: BLE001 - older PyAV
                    pass
                res = av.AudioResampler(format="s16", layout="mono", rate=16000)
                for frame in inp.decode(audio=0):
                    if cancel is not None and cancel.is_set():
                        raise InterruptedError
                    for r in res.resample(frame):
                        samples += r.samples
                        for p in st.encode(r):
                            out.mux(p)
                for r in res.resample(None):
                    samples += r.samples
                    for p in st.encode(r):
                        out.mux(p)
                for p in st.encode(None):
                    out.mux(p)
            finally:
                out.close()
        finally:
            inp.close()
    os.replace(tmp, dst)
    return samples / 16000.0


def glossary_prompt(terms: List[str]) -> Optional[str]:
    if not terms:
        return None
    text = "Glossary: " + ", ".join(terms) + "."
    return text[:800]


def friendly_error(exc: BaseException, offline: bool) -> str:
    msg = f"{type(exc).__name__}: {exc}"
    low = msg.lower()
    if "metadata_errors" in msg:
        return msg + "  ->  Fix: pip install \"av==16.0.1\" (newer PyAV does not fit faster-whisper)."
    if offline and ("localentrynotfound" in low or "offline" in low or "cannot find" in low or "snapshot" in low):
        return msg + "  ->  The model is not downloaded yet. Switch 'Offline only' off and run once with internet."
    if "no such file" in low or "filenotfound" in low:
        return msg + "  ->  The source file was moved or deleted."
    return msg


class Engine:
    def __init__(self, archive: dbm.Archive, settings: UserSettings, data_dir: str,
                 model_factory: Optional[Callable] = None):
        self.archive = archive
        self.settings = settings
        self.data_dir = data_dir
        log.set_folder(data_dir)
        self.audio_dir = os.path.join(data_dir, "audio")
        self.inbox_dir = os.path.join(data_dir, "inbox")
        self.model_factory = model_factory or self._load_model
        self._models: Dict[tuple, object] = {}
        self.jobs: List[Job] = []
        self.q: "queue.Queue[Job]" = queue.Queue()
        self.current: Optional[Job] = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._loop, name="transcriber", daemon=True)
        self.thread.start()

    # ---------- public ----------
    def submit(self, source: str, name: str = "", recorded_at: Optional[str] = None,
               delete_source: bool = False, force: bool = False,
               model: Optional[str] = None, language: Optional[str] = None) -> Job:
        source = os.path.abspath(source)
        if not os.path.isfile(source):
            raise FileNotFoundError(f"File not found: {source}")
        if recorded_at is None:
            recorded_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(source)))
        lang = self.settings.get("language") if language is None else language
        job = Job(id=uuid.uuid4().hex[:10], kind="new", name=name or os.path.splitext(os.path.basename(source))[0],
                  source=source, model=model or self.settings.get("model"), language=lang or None,
                  recorded_at=recorded_at, delete_source=delete_source, force=force)
        self._enqueue(job)
        return job

    def redo(self, rec_id: int, model: Optional[str] = None, language: Optional[str] = None) -> Job:
        rec = self.archive.get_recording(rec_id)
        if rec is None:
            raise KeyError(rec_id)
        src = rec.get("source_path") if rec.get("source_path") and os.path.isfile(rec["source_path"]) else rec.get("audio_path")
        if not src or not os.path.isfile(src):
            raise FileNotFoundError("Neither the source file nor an archived copy is available.")
        lang = self.settings.get("language") if language is None else language
        job = Job(id=uuid.uuid4().hex[:10], kind="redo", name=rec["name"], source=src,
                  model=model or self.settings.get("model"), language=lang or None, rec_id=rec_id)
        self._enqueue(job)
        return job

    def cancel(self, job_id: str) -> bool:
        for j in self.jobs:
            if j.id == job_id and j.status in ("queued", "archiving", "loading", "running"):
                j.cancel.set()
                if j.status == "queued":
                    j.status, j.message = "cancelled", "Cancelled before start."
                return True
        return False

    def state(self) -> List[dict]:
        with self.lock:
            return [j.public() for j in self.jobs[-50:]]

    def busy(self) -> bool:
        return any(j.status in ("queued", "archiving", "loading", "running") for j in self.jobs)

    # ---------- internals ----------
    def _enqueue(self, job: Job) -> None:
        with self.lock:
            self.jobs.append(job)
        self.q.put(job)

    def _load_model(self, name: str, device: str, compute_type: str):
        if self.settings.get("offline"):
            os.environ["HF_HUB_OFFLINE"] = "1"
        else:
            os.environ.pop("HF_HUB_OFFLINE", None)
        from faster_whisper import WhisperModel
        return WhisperModel(name, device=device, compute_type=compute_type)

    def _model(self, name: str):
        key = (name, self.settings.get("device"), self.settings.get("compute_type"), bool(self.settings.get("offline")))
        if key not in self._models:
            self._models.clear()  # keep one model in memory
            self._models[key] = self.model_factory(name, key[1], key[2])
        return self._models[key]

    def _loop(self) -> None:
        while True:
            job = self.q.get()
            if job.status == "cancelled":
                continue
            self.current = job
            job.started = time.time()
            try:
                self._run(job)
            except InterruptedError:
                job.status, job.message = "cancelled", "Cancelled."
                if job.rec_id:
                    self.archive.update_recording(job.rec_id, status="cancelled", error="Cancelled by the user.")
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.message = friendly_error(exc, bool(self.settings.get("offline")))
                log.exc(f"job {job.name}")
                if job.rec_id:
                    self.archive.update_recording(job.rec_id, status="error", error=job.message)
            finally:
                job.finished = time.time()
                self.current = None
                if job.delete_source and job.status != "error":
                    try:
                        os.remove(job.source)
                    except OSError:
                        pass

    def _run(self, job: Job) -> None:
        a = self.archive
        if job.kind == "new":
            sha1 = sha1_of(job.source)
            dup = None if job.force else a.find_by_sha1(sha1)
            if dup:
                job.status, job.rec_id = "duplicate", dup["id"]
                job.message = f"Already in the archive as “{dup['name']}”. Use Transcribe again there for another model."
                job.progress = 100.0
                return
            job.rec_id = a.add_recording(
                name=job.name, source_name=os.path.basename(job.source),
                source_path=None if job.delete_source else job.source, source_sha1=sha1,
                recorded_at=job.recorded_at, model=job.model, language=job.language or "", status="running")
            if self.settings.get("archive_audio"):
                job.status, job.message = "archiving", "Storing a compact copy of the audio…"
                dst = os.path.join(self.audio_dir, f"{job.rec_id:05d}.opus")
                dur = archive_opus(job.source, dst, int(self.settings.get("audio_bitrate")), job.cancel)
                a.update_recording(job.rec_id, audio_path=dst, duration=dur)
        else:
            a.clear_segments(job.rec_id)
            a.update_recording(job.rec_id, status="running", error=None, model=job.model, language=job.language or "")

        if job.cancel.is_set():
            raise InterruptedError
        job.status, job.message = "loading", f"Loading model {job.model}…"
        model = self._model(job.model)

        job.status, job.message = "running", "Transcribing…"
        prompt = glossary_prompt(self.settings.glossary_terms())
        with open(job.source, "rb") as fh:  # file handle -> paths with diacritics work on Windows
            segments, info = model.transcribe(
                fh, language=job.language, vad_filter=bool(self.settings.get("vad_filter")),
                beam_size=int(self.settings.get("beam_size")), initial_prompt=prompt)
            duration = float(getattr(info, "duration", 0.0) or 0.0)
            detected = getattr(info, "language", None)
            a.update_recording(job.rec_id, duration=duration or None,
                               language=job.language or (detected or ""))
            lines = []
            for i, seg in enumerate(segments):
                if job.cancel.is_set():
                    raise InterruptedError
                text = (seg.text or "").strip()
                if not text:
                    continue
                a.add_segment(job.rec_id, i, seg.start, seg.end, text)
                lines.append(f"[{dbm.fmt_time(seg.start)}] {text}")
                if duration > 0:
                    job.progress = min(99.9, seg.end / duration * 100.0)
                job.message = f"{dbm.fmt_time(seg.end)} / {dbm.fmt_time(duration)}"

        a.update_recording(job.rec_id, status="done", error=None)
        job.status, job.progress = "done", 100.0
        job.message = f"Done in {dbm.fmt_time(time.time() - job.started)}."
        if self.settings.get("write_txt_next_to_source") and job.kind == "new" and not job.delete_source:
            try:
                with open(os.path.splitext(job.source)[0] + ".txt", "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            except OSError as exc:
                job.message += f" (TXT next to the source not written: {exc})"
