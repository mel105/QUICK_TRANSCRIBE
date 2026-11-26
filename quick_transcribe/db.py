"""
SQLite archive of recordings and transcripts.

Tables
  recordings  one row per transcribed recording (source, archived audio, model, status ...)
  segments    timed pieces of the transcript; edits keep the original text
  segments_fts full-text index of segments.text (FTS5, falls back to LIKE)

The schema is kept simple on purpose, so another tool (e.g. a project organizer)
can read it directly or link to recordings by id.

Author: MEL
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    source_name   TEXT,
    source_path   TEXT,
    source_sha1   TEXT,
    audio_path    TEXT,
    recorded_at   TEXT,
    created_at    TEXT NOT NULL,
    duration      REAL,
    model         TEXT,
    language      TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    error         TEXT,
    note          TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_rec_sha1 ON recordings(source_sha1);
CREATE TABLE IF NOT EXISTS segments (
    id            INTEGER PRIMARY KEY,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    start         REAL NOT NULL,
    end           REAL NOT NULL,
    text          TEXT NOT NULL,
    original_text TEXT NOT NULL,
    edited        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_seg_rec ON segments(recording_id, idx);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text, content='segments', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS seg_ai AFTER INSERT ON segments BEGIN
  INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS seg_ad AFTER DELETE ON segments BEGIN
  INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS seg_au AFTER UPDATE OF text ON segments BEGIN
  INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
"""

SCHEMA_VERSION = "1"


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Archive:
    """Thread-safe wrapper; every call opens its own short transaction."""

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        try:
            self.conn.executescript(FTS)
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False
        self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        # recordings left 'running' by a crash cannot continue
        self.conn.execute("UPDATE recordings SET status='error', error='Interrupted (the app was closed).' "
                          "WHERE status IN ('running', 'queued', 'loading')")
        self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    # ---------- recordings ----------
    def add_recording(self, **fields) -> int:
        fields.setdefault("created_at", now())
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with self.lock:
            cur = self.conn.execute(f"INSERT INTO recordings ({cols}) VALUES ({marks})", tuple(fields.values()))
            self.conn.commit()
            return int(cur.lastrowid)

    def update_recording(self, rec_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE recordings SET {sets} WHERE id = ?", (*fields.values(), rec_id))
            self.conn.commit()

    def get_recording(self, rec_id: int) -> Optional[Dict[str, Any]]:
        with self.lock:
            r = self.conn.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,)).fetchone()
        return dict(r) if r else None

    def find_by_sha1(self, sha1: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            r = self.conn.execute("SELECT * FROM recordings WHERE source_sha1 = ? AND status = 'done' "
                                  "ORDER BY id DESC LIMIT 1", (sha1,)).fetchone()
        return dict(r) if r else None

    def list_recordings(self) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT r.*, (SELECT COUNT(*) FROM segments s WHERE s.recording_id = r.id) AS n_segments, "
                "(SELECT COUNT(*) FROM segments s WHERE s.recording_id = r.id AND s.edited = 1) AS n_edited "
                "FROM recordings r ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.id DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_recording(self, rec_id: int) -> Optional[Dict[str, Any]]:
        rec = self.get_recording(rec_id)
        with self.lock:
            self.conn.execute("DELETE FROM segments WHERE recording_id = ?", (rec_id,))
            self.conn.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
            self.conn.commit()
        return rec

    # ---------- segments ----------
    def clear_segments(self, rec_id: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM segments WHERE recording_id = ?", (rec_id,))
            self.conn.commit()

    def add_segment(self, rec_id: int, idx: int, start: float, end: float, text: str) -> int:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO segments (recording_id, idx, start, end, text, original_text) VALUES (?, ?, ?, ?, ?, ?)",
                (rec_id, idx, float(start), float(end), text, text))
            self.conn.commit()
            return int(cur.lastrowid)

    def segments(self, rec_id: int, after_idx: int = -1) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM segments WHERE recording_id = ? AND idx > ? ORDER BY idx",
                                     (rec_id, after_idx)).fetchall()
        return [dict(r) for r in rows]

    def edit_segment(self, seg_id: int, text: str) -> Dict[str, Any]:
        with self.lock:
            row = self.conn.execute("SELECT * FROM segments WHERE id = ?", (seg_id,)).fetchone()
            if row is None:
                raise KeyError(seg_id)
            edited = 0 if text == row["original_text"] else 1
            self.conn.execute("UPDATE segments SET text = ?, edited = ? WHERE id = ?", (text, edited, seg_id))
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM segments WHERE id = ?", (seg_id,)).fetchone()
        return dict(row)

    def replace_all(self, rec_id: int, find: str, repl: str, whole_word: bool = True) -> int:
        """Replace a term in every segment of one recording (e.g. a misheard name). Returns the count."""
        import re
        if not find:
            return 0
        pat = re.compile((r"\b" + re.escape(find) + r"\b") if whole_word else re.escape(find), re.IGNORECASE)
        n = 0
        for s in self.segments(rec_id):
            new, k = pat.subn(repl, s["text"])
            if k:
                self.edit_segment(s["id"], new)
                n += k
        return n

    # ---------- search ----------
    def search(self, query: str, limit: int = 200) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        with self.lock:
            if self.fts:
                terms = [t.replace('"', '""') for t in q.split() if t]
                match = " ".join(f'"{t}"*' for t in terms)
                try:
                    rows = self.conn.execute(
                        "SELECT s.id, s.recording_id, s.idx, s.start, s.text, r.name "
                        "FROM segments_fts f JOIN segments s ON s.id = f.rowid "
                        "JOIN recordings r ON r.id = s.recording_id "
                        "WHERE segments_fts MATCH ? ORDER BY r.id DESC, s.idx LIMIT ?", (match, limit)).fetchall()
                    return [dict(r) for r in rows]
                except sqlite3.OperationalError:
                    pass
            like = f"%{q}%"
            rows = self.conn.execute(
                "SELECT s.id, s.recording_id, s.idx, s.start, s.text, r.name FROM segments s "
                "JOIN recordings r ON r.id = s.recording_id WHERE s.text LIKE ? "
                "ORDER BY r.id DESC, s.idx LIMIT ?", (like, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---------- backup ----------
    def backup_to(self, target: str) -> None:
        with self.lock:
            dst = sqlite3.connect(target)
            try:
                self.conn.backup(dst)
            finally:
                dst.close()


def fmt_time(t: float) -> str:
    t = max(0.0, float(t or 0))
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_srt(t: float) -> str:
    t = max(0.0, float(t or 0))
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        t, ms = t + 1, 0
    return f"{fmt_time(t)},{ms:03d}"


def export_text(rec: Dict[str, Any], segs: List[Dict[str, Any]], fmt: str = "txt") -> str:
    if fmt == "srt":
        out = []
        for n, s in enumerate(segs, 1):
            out.append(f"{n}\n{fmt_srt(s['start'])} --> {fmt_srt(s['end'])}\n{s['text'].strip()}\n")
        return "\n".join(out)
    if fmt == "md":
        head = [f"# {rec['name']}", "",
                f"- Recorded: {rec.get('recorded_at') or '-'}",
                f"- Duration: {fmt_time(rec.get('duration') or 0)}",
                f"- Model: {rec.get('model') or '-'} · language: {rec.get('language') or 'auto'}",
                f"- Source file: {rec.get('source_name') or '-'}",
                "", "## Transcript", ""]
        body = [f"**[{fmt_time(s['start'])}]** {s['text'].strip()}  " for s in segs]
        return "\n".join(head + body) + "\n"
    if fmt == "plain":
        return " ".join(s["text"].strip() for s in segs) + "\n"
    return "\n".join(f"[{fmt_time(s['start'])}] {s['text'].strip()}" for s in segs) + "\n"


def default_db_path(folder: str) -> str:
    return os.path.join(folder, "transcripts.db")
