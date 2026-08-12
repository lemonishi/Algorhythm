"""Connection and schema. The schema is created on connect; there is one
version and no migration machinery until there is a second version."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule (
  slug              TEXT PRIMARY KEY,
  due_at            TEXT    NOT NULL,
  interval_days     REAL    NOT NULL,
  ease              REAL    NOT NULL,
  reps              INTEGER NOT NULL,
  lapses            INTEGER NOT NULL,
  last_grade        TEXT,
  last_reviewed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_schedule_due ON schedule(due_at);

CREATE TABLE IF NOT EXISTS reviews (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  slug              TEXT    NOT NULL,
  reviewed_at       TEXT    NOT NULL,
  grade             TEXT    NOT NULL,
  proposed_grade    TEXT,
  interval_before   REAL    NOT NULL,
  interval_after    REAL    NOT NULL,
  ease_before       REAL    NOT NULL,
  ease_after        REAL    NOT NULL,
  elapsed_ms        INTEGER,
  tests_passed      INTEGER,
  tests_total       INTEGER,
  language          TEXT    NOT NULL,
  model             TEXT,
  review_text       TEXT
);

CREATE INDEX IF NOT EXISTS idx_reviews_slug ON reviews(slug, reviewed_at);

CREATE TABLE IF NOT EXISTS attempts (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  slug      TEXT NOT NULL,
  saved_at  TEXT NOT NULL,
  language  TEXT NOT NULL,
  source    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_slug ON attempts(slug, saved_at);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn
