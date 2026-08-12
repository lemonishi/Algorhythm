"""Filesystem locations. `ALGORHYTHM_HOME` overrides everything, which is
how tests get an isolated data root."""

from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    override = os.environ.get("ALGORHYTHM_HOME")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "algorhythm"


def problems_dir() -> Path:
    return data_root() / "problems"


def attempts_dir() -> Path:
    return data_root() / "attempts"


def cache_dir() -> Path:
    return data_root() / "cache"


def db_path() -> Path:
    return data_root() / "algorhythm.db"
