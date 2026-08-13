# algorhythm v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a terminal application that schedules LeetCode practice with spaced repetition, runs solutions against local tests, and has a local LLM review how far each solution is from the reference.

**Architecture:** A Python CLI with seven decoupled packages. Problem content lives as directories on disk; scheduling state lives in SQLite behind a single repository module. Solutions are solved in nvim, executed as batched subprocesses with per-case timeouts, and reviewed by a local Ollama model whose prompt is grounded with the reference solution and concrete test results. All scheduling arithmetic is deterministic and pure.

**Tech Stack:** Python 3.11+, Typer (CLI), Textual (TUI), httpx (Ollama + LeetCode), sqlite3 (stdlib), pytest. No LangChain. No LangGraph in v1.

**Spec:** `docs/superpowers/specs/2026-08-11-algorhythm-design.md`

## Global Constraints

- Python 3.11 or later. Use `X | None` unions, `match` where it reads well, and `tomllib`.
- Dependencies limited to: `typer`, `textual`, `httpx`, `pytest`, `pytest-cov`. Anything else requires justification in the commit message.
- `algorhythm/store/repository.py` is the **only** module permitted to contain queries (SELECT/INSERT/UPDATE/DELETE). `algorhythm/store/db.py` owns connection lifecycle and schema DDL. No SQL of any kind outside the `store/` package.
- No network access in any test. LeetCode responses are recorded fixtures; Ollama is mocked.
- Every module in `scheduler/` is pure — no I/O, no clock reads. Callers pass `now` explicitly.
- All timestamps are ISO 8601 UTC strings in storage, `datetime` objects with `tzinfo=timezone.utc` in memory.
- Data root defaults to `~/.local/share/algorhythm/`, overridable via `ALGORHYTHM_HOME` for tests.
- Grades are exactly: `again`, `hard`, `good`, `easy`.
- Solution languages are exactly: `python`, `cpp`.
- Model default: `qwen2.5-coder:7b` at `http://localhost:11434`.
- Nothing may block the SRS loop. Every failure path must still permit finishing and grading a rep.

---

## File Structure

| Path | Responsibility |
|---|---|
| `algorhythm/config.py` | Data root resolution, defaults, `ALGORHYTHM_HOME` |
| `algorhythm/scheduler/sm2.py` | SM-2 arithmetic. Pure functions, no I/O |
| `algorhythm/scheduler/queue.py` | Due-queue assembly: reviews first, then new introductions, capped |
| `algorhythm/store/db.py` | Connection, schema creation, migrations |
| `algorhythm/store/repository.py` | The only SQL in the codebase |
| `algorhythm/catalog/models.py` | `Problem`, `Example`, `TestCase`, `ParamSpec` dataclasses |
| `algorhythm/catalog/store.py` | Read/write problem directories |
| `algorhythm/catalog/fetch.py` | LeetCode GraphQL client |
| `algorhythm/catalog/render.py` | Statement HTML → Markdown |
| `algorhythm/catalog/visualize.py` | ASCII trees, grids, linked lists |
| `algorhythm/codecs/leetcode_types.py` | TreeNode/ListNode build + serialize (Python side) |
| `algorhythm/runner/harness.py` | Orchestration: batching, parallelism, timeouts, result shaping |
| `algorhythm/runner/_pyharness.py` | Standalone script executed in the solution subprocess |
| `algorhythm/runner/python_runner.py` | Python execution strategy |
| `algorhythm/runner/cpp_runner.py` | C++ compile cache + execution strategy |
| `algorhythm/runner/cpp/harness.cpp` | C++ harness main() |
| `algorhythm/runner/cpp/leetcode_types.h` | C++ TreeNode/ListNode codecs |
| `algorhythm/oracle.py` | Edge-case input generation; expected outputs from the reference |
| `algorhythm/reviewer/protocol.py` | `Reviewer` Protocol — the swap seam |
| `algorhythm/reviewer/prompt.py` | Prompt construction |
| `algorhythm/reviewer/ollama.py` | Ollama implementation |
| `algorhythm/editor/session.py` | nvim workspace setup and launch |
| `algorhythm/editor/lua/algorhythm.lua` | Splits, `:w` hook, `:Review` command |
| `algorhythm/tui/app.py` | Textual application: queue and grade confirmation |
| `algorhythm/cli.py` | Typer entry point |

---

## Task 1: Project scaffolding and the SM-2 algorithm

Scaffolding is folded in here because the scheduler is the first thing that needs a test runner, and SM-2 is the highest-value place to start: it is pure, it is where a silent bug costs months of wrong scheduling, and it has no dependencies.

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `algorhythm/__init__.py`
- Create: `algorhythm/scheduler/__init__.py`
- Create: `algorhythm/scheduler/sm2.py`
- Test: `tests/scheduler/test_sm2.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Grade` (str enum: `AGAIN`/`HARD`/`GOOD`/`EASY`), `SchedulingState(interval_days: float, ease: float, reps: int, lapses: int)`, `NEW: SchedulingState`, `review(state: SchedulingState, grade: Grade) -> SchedulingState`, `due_at(state: SchedulingState, now: datetime) -> datetime`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "algorhythm"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["typer>=0.12", "textual>=0.79", "httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0"]

[project.scripts]
algorhythm = "algorhythm.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.setuptools.packages.find]
include = ["algorhythm*"]
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.DS_Store
```

- [ ] **Step 3: Create empty package markers**

```bash
mkdir -p algorhythm/scheduler tests/scheduler
touch algorhythm/__init__.py algorhythm/scheduler/__init__.py
touch tests/__init__.py tests/scheduler/__init__.py
```

- [ ] **Step 4: Write the failing tests**

Create `tests/scheduler/test_sm2.py`:

```python
from datetime import datetime, timezone

import pytest

from algorhythm.scheduler.sm2 import (
    EASE_CEILING,
    EASE_FLOOR,
    NEW,
    Grade,
    SchedulingState,
    due_at,
    review,
)


def test_new_card_intervals_are_multi_day():
    """A card here costs 20-45 minutes, so no interval starts at one day
    except a lapse. These four values are the whole point of the tuning."""
    assert review(NEW, Grade.AGAIN).interval_days == 1.0
    assert review(NEW, Grade.HARD).interval_days == 2.0
    assert review(NEW, Grade.GOOD).interval_days == 3.0
    assert review(NEW, Grade.EASY).interval_days == 5.0


def test_new_card_does_not_adjust_ease():
    for grade in Grade:
        assert review(NEW, grade).ease == NEW.ease


def test_good_multiplies_by_ease():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    assert review(state, Grade.GOOD).interval_days == 25.0


def test_good_leaves_ease_unchanged():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    assert review(state, Grade.GOOD).ease == 2.5


def test_hard_uses_fixed_multiplier_and_lowers_ease():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    result = review(state, Grade.HARD)
    assert result.interval_days == 12.0
    assert result.ease == pytest.approx(2.35)


def test_easy_applies_bonus_and_raises_ease():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    result = review(state, Grade.EASY)
    assert result.interval_days == pytest.approx(32.5)
    assert result.ease == pytest.approx(2.65)


def test_again_softens_rather_than_resetting():
    """Anki resets a lapse to ~1 day. A 20-minute card can't afford that."""
    state = SchedulingState(interval_days=30.0, ease=2.5, reps=5, lapses=0)
    result = review(state, Grade.AGAIN)
    assert result.interval_days == 9.0
    assert result.ease == pytest.approx(2.3)
    assert result.lapses == 1


def test_again_never_drops_below_one_day():
    state = SchedulingState(interval_days=2.0, ease=2.5, reps=2, lapses=0)
    assert review(state, Grade.AGAIN).interval_days == 1.0


def test_ease_floors_at_minimum():
    state = SchedulingState(interval_days=10.0, ease=EASE_FLOOR, reps=9, lapses=4)
    assert review(state, Grade.AGAIN).ease == EASE_FLOOR


def test_ease_ceilings_at_maximum():
    state = SchedulingState(interval_days=10.0, ease=EASE_CEILING, reps=9, lapses=0)
    assert review(state, Grade.EASY).ease == EASE_CEILING


def test_reps_increment_on_every_grade():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=1)
    for grade in Grade:
        assert review(state, grade).reps == 4


def test_lapses_increment_only_on_again():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=1)
    assert review(state, Grade.AGAIN).lapses == 2
    for grade in (Grade.HARD, Grade.GOOD, Grade.EASY):
        assert review(state, grade).lapses == 1


def test_realistic_good_sequence_grows_sanely():
    """Four consecutive 'good' grades from new should land in the
    weeks-to-months range, not days and not years."""
    state = NEW
    for _ in range(4):
        state = review(state, Grade.GOOD)
    assert 40.0 < state.interval_days < 60.0


def test_due_at_offsets_from_now():
    state = SchedulingState(interval_days=3.0, ease=2.5, reps=1, lapses=0)
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    assert due_at(state, now) == datetime(2026, 8, 15, tzinfo=timezone.utc)
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `python -m pytest tests/scheduler/test_sm2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.scheduler.sm2'`

- [ ] **Step 6: Implement `algorhythm/scheduler/sm2.py`**

```python
"""SM-2 spaced repetition, tuned for cards that cost 20-45 minutes.

Pure functions only. No I/O, no clock reads — callers pass `now`.

Deviations from Anki's defaults, all deliberate (see spec section 9):
  * No sub-day learning steps. You cannot re-solve a problem in ten minutes.
  * New cards start at 2-5 days rather than 1.
  * A lapse multiplies the interval by 0.3 instead of resetting it, because
    re-earning a 30-day interval costs hours of work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Grade(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


EASE_START = 2.5
EASE_FLOOR = 1.3
EASE_CEILING = 3.0

HARD_MULTIPLIER = 1.2
EASY_BONUS = 1.3
LAPSE_MULTIPLIER = 0.3
LAPSE_MIN_DAYS = 1.0

NEW_INTERVAL_DAYS: dict[Grade, float] = {
    Grade.AGAIN: 1.0,
    Grade.HARD: 2.0,
    Grade.GOOD: 3.0,
    Grade.EASY: 5.0,
}

EASE_DELTA: dict[Grade, float] = {
    Grade.AGAIN: -0.20,
    Grade.HARD: -0.15,
    Grade.GOOD: 0.0,
    Grade.EASY: 0.15,
}


@dataclass(frozen=True)
class SchedulingState:
    interval_days: float
    ease: float
    reps: int
    lapses: int


NEW = SchedulingState(interval_days=0.0, ease=EASE_START, reps=0, lapses=0)


def _clamp_ease(ease: float) -> float:
    return min(EASE_CEILING, max(EASE_FLOOR, ease))


def review(state: SchedulingState, grade: Grade) -> SchedulingState:
    """Return the state that results from grading `state` with `grade`."""
    if state.reps == 0:
        # First exposure: fixed intervals, ease untouched.
        interval = NEW_INTERVAL_DAYS[grade]
        ease = state.ease
    elif grade is Grade.AGAIN:
        interval = max(LAPSE_MIN_DAYS, state.interval_days * LAPSE_MULTIPLIER)
        ease = state.ease + EASE_DELTA[grade]
    elif grade is Grade.HARD:
        interval = state.interval_days * HARD_MULTIPLIER
        ease = state.ease + EASE_DELTA[grade]
    elif grade is Grade.GOOD:
        interval = state.interval_days * state.ease
        ease = state.ease
    else:  # Grade.EASY
        interval = state.interval_days * state.ease * EASY_BONUS
        ease = state.ease + EASE_DELTA[grade]

    return SchedulingState(
        interval_days=round(interval, 4),
        ease=round(_clamp_ease(ease), 4),
        reps=state.reps + 1,
        lapses=state.lapses + (1 if grade is Grade.AGAIN else 0),
    )


def due_at(state: SchedulingState, now: datetime) -> datetime:
    """When a card in `state` next becomes due."""
    return now + timedelta(days=state.interval_days)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/scheduler/test_sm2.py -v`
Expected: PASS — 14 passed

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore algorhythm/ tests/
git commit -m "feat(scheduler): SM-2 tuned for 20-minute cards

New cards start at 2-5 days rather than 1, and a lapse multiplies the
interval by 0.3 instead of resetting it. Both deviate from Anki because
re-earning a long interval here costs hours, not seconds."
```

---

## Task 2: SQLite store and repository

**Files:**
- Create: `algorhythm/config.py`
- Create: `algorhythm/store/__init__.py`
- Create: `algorhythm/store/db.py`
- Create: `algorhythm/store/repository.py`
- Test: `tests/store/test_repository.py`

**Interfaces:**
- Consumes: `Grade`, `SchedulingState` from Task 1.
- Produces:
  - `algorhythm.config.data_root() -> Path`
  - `algorhythm.store.db.connect(path: Path | str) -> sqlite3.Connection`
  - `ScheduleRow(slug: str, due_at: datetime, state: SchedulingState, last_grade: Grade | None, last_reviewed_at: datetime | None)`
  - `ReviewRecord(slug, reviewed_at, grade, proposed_grade, interval_before, interval_after, ease_before, ease_after, elapsed_ms, tests_passed, tests_total, language, model, review_text)`
  - `Repository(conn)` with `get_schedule(slug)`, `upsert_schedule(row)`, `due(now, limit)`, `unseen(known_slugs, limit)`, `record_review(record)`, `record_attempt(slug, saved_at, language, source)`, `last_language(slug)`, `counts()`

- [ ] **Step 1: Write `algorhythm/config.py`**

```python
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
```

- [ ] **Step 2: Write the failing tests**

Create `tests/store/test_repository.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from algorhythm.scheduler.sm2 import NEW, Grade, SchedulingState
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository, ReviewRecord, ScheduleRow

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo():
    # Yield-and-close: a returned connection is never closed, and CPython
    # emits a ResourceWarning when it is finally collected, which fails any
    # run under `-W error`.
    conn = connect(":memory:")
    try:
        yield Repository(conn)
    finally:
        conn.close()


def _row(slug: str, due: datetime, state: SchedulingState = NEW) -> ScheduleRow:
    return ScheduleRow(
        slug=slug,
        due_at=due,
        state=state,
        last_grade=None,
        last_reviewed_at=None,
    )


def test_get_schedule_returns_none_for_unknown_slug(repo):
    assert repo.get_schedule("two-sum") is None


def test_upsert_then_get_roundtrips(repo):
    state = SchedulingState(interval_days=3.0, ease=2.5, reps=1, lapses=0)
    repo.upsert_schedule(
        ScheduleRow(
            slug="two-sum",
            due_at=NOW,
            state=state,
            last_grade=Grade.GOOD,
            last_reviewed_at=NOW,
        )
    )
    got = repo.get_schedule("two-sum")
    assert got.slug == "two-sum"
    assert got.state == state
    assert got.last_grade is Grade.GOOD
    assert got.due_at == NOW


def test_upsert_is_idempotent_on_slug(repo):
    repo.upsert_schedule(_row("two-sum", NOW))
    repo.upsert_schedule(_row("two-sum", NOW + timedelta(days=5)))
    assert repo.get_schedule("two-sum").due_at == NOW + timedelta(days=5)
    assert repo.counts()["scheduled"] == 1


def test_due_excludes_future_cards(repo):
    repo.upsert_schedule(_row("past", NOW - timedelta(days=1)))
    repo.upsert_schedule(_row("future", NOW + timedelta(days=1)))
    assert [r.slug for r in repo.due(NOW, limit=10)] == ["past"]


def test_due_includes_exactly_due_cards(repo):
    repo.upsert_schedule(_row("exact", NOW))
    assert [r.slug for r in repo.due(NOW, limit=10)] == ["exact"]


def test_due_is_ordered_oldest_first(repo):
    repo.upsert_schedule(_row("recent", NOW - timedelta(days=1)))
    repo.upsert_schedule(_row("ancient", NOW - timedelta(days=30)))
    repo.upsert_schedule(_row("middle", NOW - timedelta(days=7)))
    assert [r.slug for r in repo.due(NOW, limit=10)] == ["ancient", "middle", "recent"]


def test_due_respects_limit(repo):
    for i in range(10):
        repo.upsert_schedule(_row(f"p{i}", NOW - timedelta(days=i + 1)))
    assert len(repo.due(NOW, limit=3)) == 3


def test_unseen_returns_slugs_with_no_schedule_row(repo):
    repo.upsert_schedule(_row("two-sum", NOW))
    known = ["two-sum", "add-two-numbers", "lru-cache"]
    assert repo.unseen(known, limit=10) == ["add-two-numbers", "lru-cache"]


def test_unseen_respects_limit(repo):
    assert repo.unseen(["a", "b", "c"], limit=2) == ["a", "b"]


def test_record_review_persists_and_returns_id(repo):
    record = ReviewRecord(
        slug="two-sum",
        reviewed_at=NOW,
        grade=Grade.GOOD,
        proposed_grade=Grade.HARD,
        interval_before=3.0,
        interval_after=7.5,
        ease_before=2.5,
        ease_after=2.5,
        elapsed_ms=1_800_000,
        tests_passed=8,
        tests_total=8,
        language="python",
        model="qwen2.5-coder:7b",
        review_text="Hash map is the intended approach; you used it.",
    )
    assert repo.record_review(record) == 1
    assert repo.counts()["reviews"] == 1


def test_last_language_returns_most_recent_review_language(repo):
    for lang, when in (("python", NOW - timedelta(days=2)), ("cpp", NOW)):
        repo.record_review(
            ReviewRecord(
                slug="two-sum",
                reviewed_at=when,
                grade=Grade.GOOD,
                proposed_grade=None,
                interval_before=1.0,
                interval_after=3.0,
                ease_before=2.5,
                ease_after=2.5,
                elapsed_ms=1000,
                tests_passed=1,
                tests_total=1,
                language=lang,
                model="m",
                review_text="",
            )
        )
    assert repo.last_language("two-sum") == "cpp"


def test_last_language_is_none_when_never_reviewed(repo):
    assert repo.last_language("two-sum") is None


def test_record_attempt_persists(repo):
    repo.record_attempt("two-sum", NOW, "python", "class Solution: pass")
    assert repo.counts()["attempts"] == 1
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/store -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.store'`

- [ ] **Step 4: Write `algorhythm/store/db.py`**

```python
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
```

- [ ] **Step 5: Write `algorhythm/store/repository.py`**

```python
"""The only module in the codebase permitted to contain SQL.

Keeping SQL here means a future migration off SQLite touches one file.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from algorhythm.scheduler.sm2 import Grade, SchedulingState


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True)
class ScheduleRow:
    slug: str
    due_at: datetime
    state: SchedulingState
    last_grade: Grade | None
    last_reviewed_at: datetime | None


@dataclass(frozen=True)
class ReviewRecord:
    slug: str
    reviewed_at: datetime
    grade: Grade
    proposed_grade: Grade | None
    interval_before: float
    interval_after: float
    ease_before: float
    ease_after: float
    elapsed_ms: int | None
    tests_passed: int | None
    tests_total: int | None
    language: str
    model: str | None
    review_text: str | None


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- schedule ---------------------------------------------------------

    def get_schedule(self, slug: str) -> ScheduleRow | None:
        row = self._conn.execute(
            "SELECT * FROM schedule WHERE slug = ?", (slug,)
        ).fetchone()
        return self._to_schedule_row(row) if row else None

    def upsert_schedule(self, row: ScheduleRow) -> None:
        self._conn.execute(
            """
            INSERT INTO schedule (slug, due_at, interval_days, ease, reps,
                                  lapses, last_grade, last_reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                due_at           = excluded.due_at,
                interval_days    = excluded.interval_days,
                ease             = excluded.ease,
                reps             = excluded.reps,
                lapses           = excluded.lapses,
                last_grade       = excluded.last_grade,
                last_reviewed_at = excluded.last_reviewed_at
            """,
            (
                row.slug,
                _iso(row.due_at),
                row.state.interval_days,
                row.state.ease,
                row.state.reps,
                row.state.lapses,
                row.last_grade.value if row.last_grade else None,
                _iso(row.last_reviewed_at) if row.last_reviewed_at else None,
            ),
        )

    def due(self, now: datetime, limit: int) -> list[ScheduleRow]:
        rows = self._conn.execute(
            "SELECT * FROM schedule WHERE due_at <= ? ORDER BY due_at ASC LIMIT ?",
            (_iso(now), limit),
        ).fetchall()
        return [self._to_schedule_row(r) for r in rows]

    def unseen(self, known_slugs: list[str], limit: int) -> list[str]:
        """Slugs from `known_slugs` that have never been scheduled, in the
        order given. Order is the caller's concern — the catalog decides
        curriculum order, not the database."""
        scheduled = {
            r["slug"] for r in self._conn.execute("SELECT slug FROM schedule")
        }
        out = [s for s in known_slugs if s not in scheduled]
        return out[:limit]

    # -- reviews and attempts ---------------------------------------------

    def record_review(self, record: ReviewRecord) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO reviews (slug, reviewed_at, grade, proposed_grade,
                                 interval_before, interval_after, ease_before,
                                 ease_after, elapsed_ms, tests_passed,
                                 tests_total, language, model, review_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.slug,
                _iso(record.reviewed_at),
                record.grade.value,
                record.proposed_grade.value if record.proposed_grade else None,
                record.interval_before,
                record.interval_after,
                record.ease_before,
                record.ease_after,
                record.elapsed_ms,
                record.tests_passed,
                record.tests_total,
                record.language,
                record.model,
                record.review_text,
            ),
        )
        return int(cur.lastrowid)

    def record_attempt(
        self, slug: str, saved_at: datetime, language: str, source: str
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO attempts (slug, saved_at, language, source) VALUES (?, ?, ?, ?)",
            (slug, _iso(saved_at), language, source),
        )
        return int(cur.lastrowid)

    def last_language(self, slug: str) -> str | None:
        row = self._conn.execute(
            "SELECT language FROM reviews WHERE slug = ? "
            "ORDER BY reviewed_at DESC LIMIT 1",
            (slug,),
        ).fetchone()
        return row["language"] if row else None

    def counts(self) -> dict[str, int]:
        return {
            "scheduled": self._scalar("SELECT COUNT(*) FROM schedule"),
            "reviews": self._scalar("SELECT COUNT(*) FROM reviews"),
            "attempts": self._scalar("SELECT COUNT(*) FROM attempts"),
        }

    # -- internals --------------------------------------------------------

    def _scalar(self, sql: str) -> int:
        return int(self._conn.execute(sql).fetchone()[0])

    @staticmethod
    def _to_schedule_row(row: sqlite3.Row) -> ScheduleRow:
        return ScheduleRow(
            slug=row["slug"],
            due_at=datetime.fromisoformat(row["due_at"]),
            state=SchedulingState(
                interval_days=row["interval_days"],
                ease=row["ease"],
                reps=row["reps"],
                lapses=row["lapses"],
            ),
            last_grade=Grade(row["last_grade"]) if row["last_grade"] else None,
            last_reviewed_at=_parse(row["last_reviewed_at"]),
        )
```

- [ ] **Step 6: Create the package marker and run the tests**

```bash
mkdir -p tests/store && touch algorhythm/store/__init__.py tests/store/__init__.py
python -m pytest tests/store -v
```

Expected: PASS — 13 passed

- [ ] **Step 7: Commit**

```bash
git add algorhythm/config.py algorhythm/store/ tests/store/
git commit -m "feat(store): SQLite schema and repository

All SQL is confined to repository.py so a future migration off SQLite
touches one file. The reviews table captures fields SM-2 never reads,
purely to keep an FSRS migration possible later."
```

---

## Task 3: Due queue

Assembles what you actually see when you run `algorhythm review`: overdue reviews first, then unseen problems to fill the remaining capacity. This is where the spec gap noted at plan time is resolved — the cap covers reviews *and* new introductions, with reviews taking priority.

**Files:**
- Create: `algorhythm/scheduler/queue.py`
- Test: `tests/scheduler/test_queue.py`

**Interfaces:**
- Consumes: `Repository`, `ScheduleRow` from Task 2.
- Produces: `QueueItem(slug: str, is_new: bool, due_at: datetime | None, state: SchedulingState)`, `QueueConfig(daily_cap: int = 5, new_per_day: int = 2)`, `build_queue(repo, catalog_slugs, now, config) -> list[QueueItem]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/scheduler/test_queue.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from algorhythm.scheduler.queue import QueueConfig, build_queue
from algorhythm.scheduler.sm2 import NEW, SchedulingState
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository, ScheduleRow

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
CATALOG = [f"p{i}" for i in range(20)]


@pytest.fixture
def repo():
    # Yield-and-close: a returned connection is never closed, and CPython
    # emits a ResourceWarning when it is finally collected, which fails any
    # run under `-W error`.
    conn = connect(":memory:")
    try:
        yield Repository(conn)
    finally:
        conn.close()


def schedule(repo, slug, days_overdue):
    repo.upsert_schedule(
        ScheduleRow(
            slug=slug,
            due_at=NOW - timedelta(days=days_overdue),
            state=SchedulingState(interval_days=5.0, ease=2.5, reps=2, lapses=0),
            last_grade=None,
            last_reviewed_at=None,
        )
    )


def test_empty_catalog_and_empty_store_gives_empty_queue(repo):
    assert build_queue(repo, [], NOW, QueueConfig()) == []


def test_new_problems_fill_an_empty_queue_up_to_new_per_day(repo):
    items = build_queue(repo, CATALOG, NOW, QueueConfig(daily_cap=5, new_per_day=2))
    assert [i.slug for i in items] == ["p0", "p1"]
    assert all(i.is_new for i in items)


def test_new_items_carry_the_new_scheduling_state(repo):
    items = build_queue(repo, CATALOG, NOW, QueueConfig(new_per_day=1))
    assert items[0].state == NEW
    assert items[0].due_at is None


def test_due_reviews_come_before_new_problems(repo):
    schedule(repo, "p5", days_overdue=3)
    items = build_queue(repo, CATALOG, NOW, QueueConfig(daily_cap=5, new_per_day=2))
    assert items[0].slug == "p5"
    assert items[0].is_new is False
    assert [i.slug for i in items[1:]] == ["p0", "p1"]


def test_reviews_are_ordered_most_overdue_first(repo):
    schedule(repo, "p1", days_overdue=1)
    schedule(repo, "p2", days_overdue=9)
    schedule(repo, "p3", days_overdue=4)
    items = build_queue(repo, CATALOG, NOW, QueueConfig(new_per_day=0))
    assert [i.slug for i in items] == ["p2", "p3", "p1"]


def test_daily_cap_bounds_the_whole_queue(repo):
    for i in range(10):
        schedule(repo, f"p{i}", days_overdue=i + 1)
    items = build_queue(repo, CATALOG, NOW, QueueConfig(daily_cap=5, new_per_day=2))
    assert len(items) == 5


def test_reviews_crowd_out_new_problems_when_at_cap(repo):
    """A heavy review day should not also introduce new material."""
    for i in range(5):
        schedule(repo, f"p{i}", days_overdue=i + 1)
    items = build_queue(repo, CATALOG, NOW, QueueConfig(daily_cap=5, new_per_day=2))
    assert all(i.is_new is False for i in items)


def test_new_problems_backfill_remaining_capacity(repo):
    schedule(repo, "p7", days_overdue=2)
    items = build_queue(repo, CATALOG, NOW, QueueConfig(daily_cap=5, new_per_day=2))
    assert len(items) == 3
    assert sum(1 for i in items if i.is_new) == 2


def test_new_per_day_is_a_ceiling_not_a_target(repo):
    items = build_queue(repo, ["only-one"], NOW, QueueConfig(new_per_day=5))
    assert len(items) == 1


def test_future_reviews_are_not_included(repo):
    repo.upsert_schedule(
        ScheduleRow(
            slug="p3",
            due_at=NOW + timedelta(days=2),
            state=NEW,
            last_grade=None,
            last_reviewed_at=None,
        )
    )
    items = build_queue(repo, CATALOG, NOW, QueueConfig(new_per_day=0))
    assert items == []


def test_already_scheduled_problems_are_never_introduced_as_new(repo):
    schedule(repo, "p0", days_overdue=-100)  # far future, not due
    items = build_queue(repo, CATALOG, NOW, QueueConfig(daily_cap=5, new_per_day=2))
    assert [i.slug for i in items] == ["p1", "p2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/scheduler/test_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.scheduler.queue'`

- [ ] **Step 3: Implement `algorhythm/scheduler/queue.py`**

```python
"""Assembles the daily queue.

Overdue reviews take priority over new material: falling behind on
retention is worse than falling behind on coverage. New problems only fill
capacity the reviews left over, which means a heavy review day introduces
nothing new — deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from algorhythm.scheduler.sm2 import NEW, SchedulingState
from algorhythm.store.repository import Repository


@dataclass(frozen=True)
class QueueConfig:
    daily_cap: int = 5
    new_per_day: int = 2


@dataclass(frozen=True)
class QueueItem:
    slug: str
    is_new: bool
    due_at: datetime | None
    state: SchedulingState


def build_queue(
    repo: Repository,
    catalog_slugs: list[str],
    now: datetime,
    config: QueueConfig,
) -> list[QueueItem]:
    """Return today's queue: due reviews oldest-first, then new problems in
    catalog order, bounded by `daily_cap` overall."""
    reviews = [
        QueueItem(slug=row.slug, is_new=False, due_at=row.due_at, state=row.state)
        for row in repo.due(now, limit=config.daily_cap)
    ]

    remaining = config.daily_cap - len(reviews)
    if remaining <= 0:
        return reviews

    new_slugs = repo.unseen(catalog_slugs, limit=min(remaining, config.new_per_day))
    introductions = [
        QueueItem(slug=slug, is_new=True, due_at=None, state=NEW) for slug in new_slugs
    ]
    return reviews + introductions
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/scheduler -v`
Expected: PASS — 25 passed (14 from Task 1, 11 here)

- [ ] **Step 5: Commit**

```bash
git add algorhythm/scheduler/queue.py tests/scheduler/test_queue.py
git commit -m "feat(scheduler): daily queue with new-problem introduction

Overdue reviews take priority; new problems only fill leftover capacity,
so a heavy review day introduces nothing new. Resolves a gap in the spec,
which capped the queue but never said how unseen problems enter it."
```

---

## Task 4: Problem model and on-disk format

**Files:**
- Create: `algorhythm/catalog/__init__.py`
- Create: `algorhythm/catalog/models.py`
- Create: `algorhythm/catalog/store.py`
- Test: `tests/catalog/test_store.py`

**Interfaces:**
- Consumes: `algorhythm.config.problems_dir`.
- Produces:
  - `ParamSpec(name: str, kind: str)` where `kind` is one of `raw`, `tree`, `linked_list`, `grid`
  - `Example(input_text: str, output_text: str, explanation: str | None)`
  - `TestCase(id: str, args: dict, expected, source: str)` where `source` is `example` or `oracle`
  - `Problem(...)` — full field list in the implementation below
  - `save_problem(problem, root=None) -> Path`, `load_problem(slug, root=None) -> Problem`
  - `list_slugs(root=None) -> list[str]`
  - `save_tests(slug, cases, root=None)`, `load_tests(slug, root=None) -> list[TestCase]`
  - `reference_path(slug, language, root=None) -> Path`, `stub_path(slug, language, root=None) -> Path`

- [ ] **Step 1: Write the failing tests**

Create `tests/catalog/test_store.py`:

```python
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Example, ParamSpec, Problem, TestCase
from algorhythm.catalog.store import (
    list_slugs,
    load_problem,
    load_tests,
    reference_path,
    save_problem,
    save_tests,
    stub_path,
)

FETCHED = datetime(2026, 8, 12, tzinfo=timezone.utc)


def make_problem(slug: str = "binary-tree-level-order-traversal") -> Problem:
    return Problem(
        slug=slug,
        number=102,
        title="Binary Tree Level Order Traversal",
        difficulty="Medium",
        topics=["Tree", "Breadth-First Search"],
        companies=["Amazon", "Meta"],
        url=f"https://leetcode.com/problems/{slug}/",
        statement_md="Given the root of a binary tree, return the level order traversal.",
        constraints=["The number of nodes is in the range [0, 2000]."],
        examples=[
            Example(
                input_text="root = [3,9,20,null,null,15,7]",
                output_text="[[3],[9,20],[15,7]]",
                explanation=None,
            )
        ],
        params=[ParamSpec(name="root", kind="tree")],
        return_kind="raw",
        entry_point="levelOrder",
        fetched_at=FETCHED,
        company_tags_source="community-mirror",
        company_tags_asof="2025-03-01",
    )


def test_save_creates_the_expected_files(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    d = tmp_path / "0102-binary-tree-level-order-traversal"
    assert (d / "meta.json").exists()
    assert (d / "statement.md").exists()
    assert (d / "examples.json").exists()


def test_statement_is_written_as_plain_markdown(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    text = (
        tmp_path / "0102-binary-tree-level-order-traversal" / "statement.md"
    ).read_text()
    assert "Given the root of a binary tree" in text


def test_roundtrip_preserves_every_field(tmp_path):
    original = make_problem()
    save_problem(original, root=tmp_path)
    assert load_problem(original.slug, root=tmp_path) == original


def test_roundtrip_preserves_param_kinds(tmp_path):
    original = make_problem()
    save_problem(original, root=tmp_path)
    loaded = load_problem(original.slug, root=tmp_path)
    assert loaded.params == [ParamSpec(name="root", kind="tree")]


def test_load_missing_problem_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_problem("does-not-exist", root=tmp_path)


def test_list_slugs_is_sorted_by_problem_number(tmp_path):
    save_problem(make_problem("two-sum")._replace_number(1), root=tmp_path)
    save_problem(make_problem(), root=tmp_path)
    save_problem(make_problem("lru-cache")._replace_number(146), root=tmp_path)
    assert list_slugs(root=tmp_path) == [
        "two-sum",
        "binary-tree-level-order-traversal",
        "lru-cache",
    ]


def test_list_slugs_ignores_stray_files(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    (tmp_path / "README.md").write_text("not a problem")
    assert list_slugs(root=tmp_path) == ["binary-tree-level-order-traversal"]


def test_tests_roundtrip(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    cases = [
        TestCase(
            id="example-1",
            args={"root": [3, 9, 20, None, None, 15, 7]},
            expected=[[3], [9, 20], [15, 7]],
            source="example",
        ),
        TestCase(id="edge-empty", args={"root": []}, expected=[], source="oracle"),
    ]
    save_tests("binary-tree-level-order-traversal", cases, root=tmp_path)
    assert load_tests("binary-tree-level-order-traversal", root=tmp_path) == cases


def test_load_tests_is_empty_when_none_written(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    assert load_tests("binary-tree-level-order-traversal", root=tmp_path) == []


def test_reference_and_stub_paths_use_the_right_extensions(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    slug = "binary-tree-level-order-traversal"
    assert reference_path(slug, "python", root=tmp_path).name == "reference.py"
    assert reference_path(slug, "cpp", root=tmp_path).name == "reference.cpp"
    assert stub_path(slug, "python", root=tmp_path).name == "stub.py"
    assert stub_path(slug, "cpp", root=tmp_path).name == "stub.cpp"


def test_unknown_language_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown language"):
        reference_path("any", "rust", root=tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/catalog -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.catalog'`

- [ ] **Step 3: Write `algorhythm/catalog/models.py`**

```python
"""Problem content model.

`ParamSpec.kind` is the bridge between LeetCode's JSON-array notation and the
object graphs its signatures actually take. `[3,9,20,null,null,15,7]` is a
`tree`; `[[1,1,0],[0,1,0]]` is a `grid`. The runners use this to decide how
to deserialize each argument before calling the solution.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

PARAM_KINDS = frozenset({"raw", "tree", "linked_list", "grid"})
LANGUAGES = {"python": "py", "cpp": "cpp"}


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: str = "raw"

    def __post_init__(self) -> None:
        if self.kind not in PARAM_KINDS:
            raise ValueError(f"unknown param kind: {self.kind}")


@dataclass(frozen=True)
class Example:
    input_text: str
    output_text: str
    explanation: str | None = None


@dataclass(frozen=True)
class TestCase:
    # Not a pytest test class, despite the name — this tells pytest's
    # `Test*` collection heuristic to leave it alone.
    __test__ = False

    id: str
    args: dict[str, Any]
    expected: Any
    source: str  # "example" | "oracle"


@dataclass(frozen=True)
class Problem:
    slug: str
    number: int
    title: str
    difficulty: str
    topics: list[str]
    companies: list[str]
    url: str
    statement_md: str
    constraints: list[str]
    examples: list[Example]
    params: list[ParamSpec]
    return_kind: str
    entry_point: str
    fetched_at: datetime
    company_tags_source: str | None = None
    company_tags_asof: str | None = None

    @property
    def dirname(self) -> str:
        return f"{self.number:04d}-{self.slug}"

    def _replace_number(self, number: int) -> "Problem":
        """Test helper; also handy when correcting a bad fetch by hand."""
        return replace(self, number=number)
```

- [ ] **Step 4: Write `algorhythm/catalog/store.py`**

```python
"""Reading and writing problem directories.

Content lives on disk rather than in SQLite so it stays greppable,
diffable, and fixable in an editor when a fetch comes out mangled.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from algorhythm import config
from algorhythm.catalog.models import (
    LANGUAGES,
    Example,
    ParamSpec,
    Problem,
    TestCase,
)


def _root(root: Path | None) -> Path:
    return root if root is not None else config.problems_dir()


def _slug_of(directory: Path) -> str:
    """Strip the numeric prefix: `0102-level-order` -> `level-order`."""
    _, _, slug = directory.name.partition("-")
    return slug


def _problem_number(directory: Path) -> int | None:
    """The leading problem number, or None if this isn't one of our directories.

    `isdecimal()` rather than `isdigit()`: the latter is True for superscript
    and circled digits (`²`, `①`) that `int()` then rejects, which would put
    the crash back that this guard exists to prevent.
    """
    prefix, _, _ = directory.name.partition("-")
    return int(prefix) if prefix.isdecimal() else None


def _dir_for(slug: str, root: Path | None) -> Path:
    """Resolve a slug to its directory by EXACT match on the un-prefixed name.

    Suffix matching (`glob(f"*-{slug}")`) is wrong here: LeetCode has both
    `path-sum` and `binary-tree-maximum-path-sum`, and a glob for the former
    matches the latter's directory.
    """
    base = _root(root)
    matches = sorted(d for d in base.glob("*-*") if d.is_dir() and _slug_of(d) == slug)
    if not matches:
        raise FileNotFoundError(f"no problem directory for slug {slug!r} under {base}")
    if len(matches) > 1:
        names = ", ".join(d.name for d in matches)
        raise FileNotFoundError(f"ambiguous slug {slug!r}: matches {names}")
    return matches[0]


def save_problem(problem: Problem, root: Path | None = None) -> Path:
    d = _root(root) / problem.dirname
    d.mkdir(parents=True, exist_ok=True)

    meta = {
        "slug": problem.slug,
        "number": problem.number,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "topics": problem.topics,
        "companies": problem.companies,
        "url": problem.url,
        "constraints": problem.constraints,
        "params": [asdict(p) for p in problem.params],
        "return_kind": problem.return_kind,
        "entry_point": problem.entry_point,
        "fetched_at": problem.fetched_at.isoformat(),
        "company_tags_source": problem.company_tags_source,
        "company_tags_asof": problem.company_tags_asof,
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (d / "statement.md").write_text(problem.statement_md.rstrip() + "\n")
    (d / "examples.json").write_text(
        json.dumps([asdict(e) for e in problem.examples], indent=2) + "\n"
    )
    return d


def load_problem(slug: str, root: Path | None = None) -> Problem:
    d = _dir_for(slug, root)
    meta = json.loads((d / "meta.json").read_text())
    examples = [Example(**e) for e in json.loads((d / "examples.json").read_text())]
    return Problem(
        slug=meta["slug"],
        number=meta["number"],
        title=meta["title"],
        difficulty=meta["difficulty"],
        topics=meta["topics"],
        companies=meta["companies"],
        url=meta["url"],
        statement_md=(d / "statement.md").read_text().rstrip(),
        constraints=meta["constraints"],
        examples=examples,
        params=[ParamSpec(**p) for p in meta["params"]],
        return_kind=meta["return_kind"],
        entry_point=meta["entry_point"],
        fetched_at=datetime.fromisoformat(meta["fetched_at"]),
        company_tags_source=meta.get("company_tags_source"),
        company_tags_asof=meta.get("company_tags_asof"),
    )


def list_slugs(root: Path | None = None) -> list[str]:
    """Slugs in curriculum order, i.e. by problem number.

    Sorts on the parsed integer prefix rather than the directory string, so
    ordering stays correct past four digits.
    """
    base = _root(root)
    if not base.exists():
        return []

    numbered: list[tuple[int, Path]] = []
    for directory in base.iterdir():
        if not (directory.is_dir() and (directory / "meta.json").exists()):
            continue
        number = _problem_number(directory)
        if number is None:
            continue  # not a directory this module owns; ignore rather than crash
        numbered.append((number, directory))

    numbered.sort(key=lambda pair: pair[0])
    return [_slug_of(directory) for _, directory in numbered]


def save_tests(slug: str, cases: list[TestCase], root: Path | None = None) -> Path:
    d = _dir_for(slug, root)
    path = d / "tests.json"
    path.write_text(json.dumps([asdict(c) for c in cases], indent=2) + "\n")
    return path


def load_tests(slug: str, root: Path | None = None) -> list[TestCase]:
    path = _dir_for(slug, root) / "tests.json"
    if not path.exists():
        return []
    return [TestCase(**c) for c in json.loads(path.read_text())]


def _ext(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"unknown language: {language}")
    return LANGUAGES[language]


def reference_path(slug: str, language: str, root: Path | None = None) -> Path:
    ext = _ext(language)
    return _dir_for(slug, root) / f"reference.{ext}"


def stub_path(slug: str, language: str, root: Path | None = None) -> Path:
    ext = _ext(language)
    return _dir_for(slug, root) / f"stub.{ext}"
```

- [ ] **Step 5: Create package markers and run the tests**

```bash
mkdir -p tests/catalog && touch algorhythm/catalog/__init__.py tests/catalog/__init__.py
python -m pytest tests/catalog -v
```

Expected: PASS — 11 passed

Note: `test_unknown_language_raises` calls `reference_path` with a slug that has no directory. Order matters — `_ext` must be called before `_dir_for` so the `ValueError` surfaces rather than `FileNotFoundError`. The implementation above does this correctly.

- [ ] **Step 6: Commit**

```bash
git add algorhythm/catalog/ tests/catalog/
git commit -m "feat(catalog): problem model and on-disk format

Content lives on disk rather than SQLite so it stays greppable, diffable,
and fixable in an editor when a fetch comes out mangled. ParamSpec.kind
bridges LeetCode's JSON arrays and the object graphs its signatures take."
```

---

## Task 5: LeetCode GraphQL fetcher

**Files:**
- Create: `algorhythm/catalog/fetch.py`
- Create: `tests/catalog/fixtures/level_order.json`
- Test: `tests/catalog/test_fetch.py`

**Interfaces:**
- Consumes: `Problem`, `Example`, `ParamSpec` from Task 4; `render_statement` from Task 6 is **not** used here — this task stores raw HTML in `statement_md` and Task 6 replaces that call. To avoid a forward dependency, `parse_question` takes an optional `render` callable defaulting to identity.
- Produces:
  - `GRAPHQL_URL: str`, `QUESTION_QUERY: str`
  - `parse_question(payload: dict, *, fetched_at: datetime, render=None) -> Problem`
  - `fetch_question(slug: str, *, client=None) -> Problem`
  - `FetchError(Exception)`

- [ ] **Step 1: Record the fixture**

Create `tests/catalog/fixtures/level_order.json`. This is a trimmed but structurally faithful capture of a real response:

```json
{
  "data": {
    "question": {
      "questionFrontendId": "102",
      "title": "Binary Tree Level Order Traversal",
      "titleSlug": "binary-tree-level-order-traversal",
      "difficulty": "Medium",
      "content": "<p>Given the <code>root</code> of a binary tree, return <em>the level order traversal of its nodes' values</em>.</p>\n<p><strong class=\"example\">Example 1:</strong></p>\n<pre><strong>Input:</strong> root = [3,9,20,null,null,15,7]\n<strong>Output:</strong> [[3],[9,20],[15,7]]\n</pre>\n<p><strong class=\"example\">Example 2:</strong></p>\n<pre><strong>Input:</strong> root = [1]\n<strong>Output:</strong> [[1]]\n</pre>\n<p><strong>Constraints:</strong></p>\n<ul>\n\t<li>The number of nodes in the tree is in the range <code>[0, 2000]</code>.</li>\n\t<li><code>-1000 &lt;= Node.val &lt;= 1000</code></li>\n</ul>\n",
      "exampleTestcases": "[3,9,20,null,null,15,7]\n[1]",
      "topicTags": [
        {"name": "Tree", "slug": "tree"},
        {"name": "Breadth-First Search", "slug": "breadth-first-search"}
      ],
      "codeSnippets": [
        {
          "lang": "Python3",
          "langSlug": "python3",
          "code": "class Solution:\n    def levelOrder(self, root: Optional[TreeNode]) -> List[List[int]]:\n        "
        },
        {
          "lang": "C++",
          "langSlug": "cpp",
          "code": "class Solution {\npublic:\n    vector<vector<int>> levelOrder(TreeNode* root) {\n        \n    }\n};"
        }
      ],
      "hints": []
    }
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/catalog/test_fetch.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from algorhythm.catalog.fetch import FetchError, parse_question

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED = datetime(2026, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def payload():
    return json.loads((FIXTURES / "level_order.json").read_text())


def test_parses_identity_fields(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.slug == "binary-tree-level-order-traversal"
    assert p.number == 102
    assert p.title == "Binary Tree Level Order Traversal"
    assert p.difficulty == "Medium"


def test_parses_topic_tags(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.topics == ["Tree", "Breadth-First Search"]


def test_companies_are_empty_because_they_are_premium_only(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.companies == []
    assert p.company_tags_source is None


def test_builds_the_canonical_url(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.url == "https://leetcode.com/problems/binary-tree-level-order-traversal/"


def test_extracts_both_examples(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert len(p.examples) == 2
    assert p.examples[0].input_text == "root = [3,9,20,null,null,15,7]"
    assert p.examples[0].output_text == "[[3],[9,20],[15,7]]"
    assert p.examples[1].input_text == "root = [1]"


def test_extracts_constraints_as_plain_text(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.constraints == [
        "The number of nodes in the tree is in the range [0, 2000].",
        "-1000 <= Node.val <= 1000",
    ]


def test_derives_entry_point_from_the_python_snippet(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.entry_point == "levelOrder"


def test_derives_param_names_and_infers_tree_kind(payload):
    """`root: Optional[TreeNode]` must become kind='tree' or the runner will
    hand the solution a raw list and every test will fail confusingly."""
    p = parse_question(payload, fetched_at=FETCHED)
    assert [(x.name, x.kind) for x in p.params] == [("root", "tree")]


def test_render_hook_is_applied_to_the_statement(payload):
    p = parse_question(payload, fetched_at=FETCHED, render=lambda html: "RENDERED")
    assert p.statement_md == "RENDERED"


def test_statement_defaults_to_raw_content_without_a_render_hook(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert "<p>" in p.statement_md


def test_missing_question_raises_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        parse_question({"data": {"question": None}}, fetched_at=FETCHED)


def test_graphql_errors_raise_fetch_error():
    payload = {"errors": [{"message": "boom"}]}
    with pytest.raises(FetchError, match="boom"):
        parse_question(payload, fetched_at=FETCHED)


def test_stub_extraction_returns_both_languages(payload):
    from algorhythm.catalog.fetch import extract_stubs

    stubs = extract_stubs(payload["data"]["question"])
    assert set(stubs) == {"python", "cpp"}
    assert "def levelOrder" in stubs["python"]
    assert "vector<vector<int>> levelOrder" in stubs["cpp"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/catalog/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.catalog.fetch'`

- [ ] **Step 4: Implement `algorhythm/catalog/fetch.py`**

```python
"""LeetCode GraphQL client.

Uses the same public endpoint LeetCode's own frontend uses. No auth needed
for public problems.

Available: statement, examples, constraints, difficulty, topic tags, and
codeSnippets (the real per-language signatures, used verbatim as our stubs).

Not available: reference solutions, the hidden judge suite, and company
tags — all Premium. Those are sourced elsewhere.

This module is the single point of contact with LeetCode's schema. When
they change it, everything that breaks breaks here.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Callable

from algorhythm.catalog.models import Example, ParamSpec, Problem

GRAPHQL_URL = "https://leetcode.com/graphql"

QUESTION_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId
    title
    titleSlug
    difficulty
    content
    exampleTestcases
    topicTags { name slug }
    codeSnippets { lang langSlug code }
    hints
  }
}
"""

LANG_SLUGS = {"python3": "python", "cpp": "cpp"}

# Maps a Python type annotation fragment to the deserialization kind the
# runners need. Order matters: check the most specific first.
_KIND_HINTS = (
    ("TreeNode", "tree"),
    ("ListNode", "linked_list"),
    ("List[List[", "grid"),
)


class FetchError(Exception):
    pass


def _strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _extract_examples(content: str) -> list[Example]:
    """LeetCode wraps each worked example in a <pre> block with bolded
    Input/Output/Explanation labels."""
    examples: list[Example] = []
    for block in re.findall(r"<pre>(.*?)</pre>", content, flags=re.S):
        text = _strip_tags(block)
        fields: dict[str, list[str]] = {}
        current: str | None = None
        for line in text.splitlines():
            match = re.match(r"\s*(Input|Output|Explanation):\s*(.*)", line)
            if match:
                current = match.group(1).lower()
                fields[current] = [match.group(2).strip()]
            elif current:
                fields[current].append(line.strip())
        if "input" not in fields or "output" not in fields:
            continue
        explanation = " ".join(fields.get("explanation", [])).strip() or None
        examples.append(
            Example(
                input_text=" ".join(fields["input"]).strip(),
                output_text=" ".join(fields["output"]).strip(),
                explanation=explanation,
            )
        )
    return examples


def _extract_constraints(content: str) -> list[str]:
    match = re.search(
        r"<strong>Constraints:</strong>.*?<ul>(.*?)</ul>", content, flags=re.S
    )
    if not match:
        return []
    items = re.findall(r"<li>(.*?)</li>", match.group(1), flags=re.S)
    return [_strip_tags(item) for item in items if _strip_tags(item)]


def extract_stubs(question: dict[str, Any]) -> dict[str, str]:
    """Per-language starter code, keyed by our language names."""
    out: dict[str, str] = {}
    for snippet in question.get("codeSnippets") or []:
        name = LANG_SLUGS.get(snippet.get("langSlug"))
        if name:
            out[name] = snippet["code"]
    return out


def _parse_python_signature(code: str) -> tuple[str, list[ParamSpec]]:
    """Pull the method name and parameters out of the Python stub.

    `def levelOrder(self, root: Optional[TreeNode]) -> List[List[int]]:`
    becomes ("levelOrder", [ParamSpec("root", "tree")]).
    """
    match = re.search(r"def\s+(\w+)\s*\(self\s*,?\s*(.*?)\)\s*->", code, flags=re.S)
    if not match:
        raise FetchError("could not parse the Python stub signature")

    entry_point = match.group(1)
    params: list[ParamSpec] = []
    depth = 0
    current = ""
    for char in match.group(2) + ",":
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if char == "," and depth == 0:
            if current.strip():
                params.append(_param_from_fragment(current))
            current = ""
        else:
            current += char
    return entry_point, params


def _param_from_fragment(fragment: str) -> ParamSpec:
    name, _, annotation = fragment.partition(":")
    kind = "raw"
    for needle, candidate in _KIND_HINTS:
        if needle in annotation:
            kind = candidate
            break
    return ParamSpec(name=name.strip(), kind=kind)


def _return_kind(code: str) -> str:
    """The deserialization kind for the RETURN value.

    `grid` is deliberately excluded, unlike `_param_from_fragment`. The two
    are asymmetric because they are consumed differently: parameter kinds
    drive both `decode()` and `visualize()`, but `return_kind` is only ever
    passed to `encode()` — and there `grid` and `raw` are the same identity
    function, because a returned nested list is already comparable JSON.
    Reporting `grid` here would add a distinction nothing acts on.
    """
    match = re.search(r"->\s*(.+?):", code)
    if not match:
        return "raw"
    annotation = match.group(1)
    for needle, candidate in _KIND_HINTS:
        if needle in annotation and candidate != "grid":
            return candidate
    return "raw"


def parse_question(
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
    render: Callable[[str], str] | None = None,
) -> Problem:
    """Turn a GraphQL response body into a Problem.

    `render` converts the statement HTML to Markdown; when omitted the raw
    HTML is kept, which keeps this module independent of the renderer.
    """
    if payload.get("errors"):
        raise FetchError("; ".join(e.get("message", "?") for e in payload["errors"]))

    question = (payload.get("data") or {}).get("question")
    if not question:
        raise FetchError("question not found")

    content = question.get("content") or ""
    stubs = extract_stubs(question)
    if "python" not in stubs:
        raise FetchError("no Python snippet in response; cannot derive signature")

    entry_point, params = _parse_python_signature(stubs["python"])

    return Problem(
        slug=question["titleSlug"],
        number=int(question["questionFrontendId"]),
        title=question["title"],
        difficulty=question["difficulty"],
        topics=[t["name"] for t in question.get("topicTags") or []],
        companies=[],
        url=f"https://leetcode.com/problems/{question['titleSlug']}/",
        statement_md=render(content) if render else content,
        constraints=_extract_constraints(content),
        examples=_extract_examples(content),
        params=params,
        return_kind=_return_kind(stubs["python"]),
        entry_point=entry_point,
        fetched_at=fetched_at,
        company_tags_source=None,
        company_tags_asof=None,
    )


def fetch_question(slug: str, *, client=None) -> Problem:
    """Network call. Never exercised in tests — see the recorded fixtures."""
    import httpx

    from algorhythm.catalog.render import render_statement

    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        response = client.post(
            GRAPHQL_URL,
            json={"query": QUESTION_QUERY, "variables": {"titleSlug": slug}},
            headers={
                "Content-Type": "application/json",
                "Referer": f"https://leetcode.com/problems/{slug}/",
                "User-Agent": "algorhythm/0.1 (personal study tool)",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the user
        raise FetchError(f"fetching {slug!r} failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    return parse_question(
        payload, fetched_at=datetime.now(tz=timezone.utc), render=render_statement
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/catalog/test_fetch.py -v`
Expected: PASS — 13 passed

- [ ] **Step 6: Commit**

```bash
git add algorhythm/catalog/fetch.py tests/catalog/
git commit -m "feat(catalog): LeetCode GraphQL fetcher

Parses statement, examples, constraints, topic tags, and codeSnippets.
Infers ParamSpec kinds from the Python signature so the runner knows to
build a TreeNode rather than passing a raw list. Tests run entirely off
recorded fixtures, so they never hit the network and do not break when
LeetCode does."
```

---

## Task 6: LeetCode type codecs

LeetCode signatures take `TreeNode*`, `ListNode*`, and 2-D vectors, but its test data is JSON arrays. Both runners need to convert in both directions, and the ASCII visualisers need the same builders. This task owns that conversion.

**Files:**
- Create: `algorhythm/codecs/__init__.py`
- Create: `algorhythm/codecs/leetcode_types.py`
- Test: `tests/codecs/test_leetcode_types.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TreeNode(val, left, right)`, `ListNode(val, next)`
  - `build_tree(values: list) -> TreeNode | None`, `serialize_tree(root) -> list`
  - `build_linked_list(values: list) -> ListNode | None`, `serialize_linked_list(head) -> list`
  - `decode(value, kind: str)`, `encode(value, kind: str)`

- [ ] **Step 1: Write the failing tests**

Create `tests/codecs/test_leetcode_types.py`:

```python
import pytest

from algorhythm.codecs.leetcode_types import (
    ListNode,
    TreeNode,
    build_linked_list,
    build_tree,
    decode,
    encode,
    serialize_linked_list,
    serialize_tree,
)


# -- trees ----------------------------------------------------------------

def test_build_tree_of_empty_list_is_none():
    assert build_tree([]) is None


def test_build_tree_of_explicit_null_is_none():
    assert build_tree([None]) is None


def test_build_tree_sets_children_in_level_order():
    root = build_tree([1, 2, 3])
    assert root.val == 1
    assert root.left.val == 2
    assert root.right.val == 3


def test_build_tree_skips_null_children():
    """[3,9,20,null,null,15,7]: 9 is a leaf, so 15 and 7 belong to 20.
    Getting this wrong silently builds the wrong tree."""
    root = build_tree([3, 9, 20, None, None, 15, 7])
    assert root.left.val == 9
    assert root.left.left is None
    assert root.left.right is None
    assert root.right.left.val == 15
    assert root.right.right.val == 7


def test_build_tree_handles_a_left_leaning_chain():
    root = build_tree([1, 2, None, 3, None, 4])
    assert root.left.val == 2
    assert root.left.left.val == 3
    assert root.left.left.left.val == 4


def test_serialize_tree_of_none_is_empty():
    assert serialize_tree(None) == []


def test_serialize_tree_trims_trailing_nulls():
    assert serialize_tree(build_tree([1, 2, 3])) == [1, 2, 3]


@pytest.mark.parametrize(
    "values",
    [
        [1],
        [1, 2, 3],
        [3, 9, 20, None, None, 15, 7],
        [1, None, 2, None, 3],
        [5, 4, 7, 3, None, 2, None, -1, None, 9],
    ],
)
def test_tree_roundtrips(values):
    assert serialize_tree(build_tree(values)) == values


# -- linked lists ---------------------------------------------------------

def test_build_linked_list_of_empty_is_none():
    assert build_linked_list([]) is None


def test_build_linked_list_chains_nodes():
    head = build_linked_list([1, 2, 3])
    assert head.val == 1
    assert head.next.val == 2
    assert head.next.next.val == 3
    assert head.next.next.next is None


def test_serialize_linked_list_of_none_is_empty():
    assert serialize_linked_list(None) == []


@pytest.mark.parametrize("values", [[], [1], [1, 2, 3, 4, 5]])
def test_linked_list_roundtrips(values):
    assert serialize_linked_list(build_linked_list(values)) == values


# -- dispatch -------------------------------------------------------------

def test_decode_raw_passes_through_untouched():
    assert decode([1, 2, 3], "raw") == [1, 2, 3]
    assert decode("hello", "raw") == "hello"


def test_decode_grid_passes_through_untouched():
    assert decode([[1, 0], [0, 1]], "grid") == [[1, 0], [0, 1]]


def test_decode_tree_builds_a_node():
    assert isinstance(decode([1, 2], "tree"), TreeNode)


def test_decode_linked_list_builds_a_node():
    assert isinstance(decode([1, 2], "linked_list"), ListNode)


def test_encode_inverts_decode_for_trees():
    values = [3, 9, 20, None, None, 15, 7]
    assert encode(decode(values, "tree"), "tree") == values


def test_encode_inverts_decode_for_linked_lists():
    assert encode(decode([1, 2, 3], "linked_list"), "linked_list") == [1, 2, 3]


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown kind"):
        decode([1], "quaternion")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/codecs -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.codecs'`

- [ ] **Step 3: Implement `algorhythm/codecs/leetcode_types.py`**

```python
"""Conversion between LeetCode's JSON array notation and the object graphs
its signatures actually take.

The subtle part is `build_tree`. LeetCode's level-order encoding omits the
children of null nodes rather than padding them, so a naive
`2*i+1` index scheme builds the wrong tree for anything unbalanced. The
queue-based construction below is the correct reading.
"""

from __future__ import annotations

from collections import deque
from typing import Any


class TreeNode:
    __slots__ = ("val", "left", "right")

    def __init__(self, val: Any = 0, left=None, right=None) -> None:
        self.val = val
        self.left = left
        self.right = right

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TreeNode({self.val!r})"


class ListNode:
    __slots__ = ("val", "next")

    def __init__(self, val: Any = 0, next=None) -> None:  # noqa: A002
        self.val = val
        self.next = next

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ListNode({self.val!r})"


def build_tree(values: list[Any] | None) -> TreeNode | None:
    if not values or values[0] is None:
        return None

    root = TreeNode(values[0])
    queue = deque([root])
    index = 1

    while queue and index < len(values):
        node = queue.popleft()

        if index < len(values):
            value = values[index]
            index += 1
            if value is not None:
                node.left = TreeNode(value)
                queue.append(node.left)

        if index < len(values):
            value = values[index]
            index += 1
            if value is not None:
                node.right = TreeNode(value)
                queue.append(node.right)

    return root


def serialize_tree(root: TreeNode | None) -> list[Any]:
    if root is None:
        return []

    out: list[Any] = []
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if node is None:
            out.append(None)
            continue
        out.append(node.val)
        queue.append(node.left)
        queue.append(node.right)

    while out and out[-1] is None:
        out.pop()
    return out


def build_linked_list(values: list[Any] | None) -> ListNode | None:
    head: ListNode | None = None
    tail: ListNode | None = None
    for value in values or []:
        node = ListNode(value)
        if head is None:
            head = tail = node
        else:
            tail.next = node
            tail = node
    return head


def serialize_linked_list(head: ListNode | None) -> list[Any]:
    out: list[Any] = []
    seen: set[int] = set()
    node = head
    while node is not None:
        if id(node) in seen:  # a cycle; stop rather than hang
            break
        seen.add(id(node))
        out.append(node.val)
        node = node.next
    return out


_DECODERS = {
    "raw": lambda v: v,
    "grid": lambda v: v,
    "tree": build_tree,
    "linked_list": build_linked_list,
}

_ENCODERS = {
    "raw": lambda v: v,
    "grid": lambda v: v,
    "tree": serialize_tree,
    "linked_list": serialize_linked_list,
}


def decode(value: Any, kind: str) -> Any:
    """JSON -> the object the solution expects."""
    try:
        return _DECODERS[kind](value)
    except KeyError:
        raise ValueError(f"unknown kind: {kind}") from None


def encode(value: Any, kind: str) -> Any:
    """The object the solution returned -> comparable JSON."""
    try:
        return _ENCODERS[kind](value)
    except KeyError:
        raise ValueError(f"unknown kind: {kind}") from None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
mkdir -p tests/codecs && touch algorhythm/codecs/__init__.py tests/codecs/__init__.py
python -m pytest tests/codecs -v
```

Expected: PASS — 24 passed

- [ ] **Step 5: Commit**

```bash
git add algorhythm/codecs/ tests/codecs/
git commit -m "feat(codecs): LeetCode TreeNode and ListNode conversion

Level-order tree decoding omits children of null nodes rather than padding
them, so the index-arithmetic approach builds the wrong tree for anything
unbalanced. Uses queue-based construction, with a roundtrip test over five
shapes including left-leaning chains."
```

---

## Task 7: Statement rendering and ASCII visualisers

**Files:**
- Create: `algorhythm/catalog/render.py`
- Create: `algorhythm/catalog/visualize.py`
- Test: `tests/catalog/test_render.py`
- Test: `tests/catalog/test_visualize.py`

**Interfaces:**
- Consumes: `build_tree`, `TreeNode` from Task 6.
- Produces:
  - `render_statement(html: str) -> str`
  - `render_tree(values: list) -> str`
  - `render_grid(rows: list[list]) -> str`
  - `render_linked_list(values: list) -> str`
  - `visualize(values, kind: str) -> str | None`

- [ ] **Step 1: Write the failing render tests**

Create `tests/catalog/test_render.py`:

```python
from algorhythm.catalog.render import render_statement


def test_paragraphs_are_separated_by_blank_lines():
    out = render_statement("<p>First.</p><p>Second.</p>")
    assert out == "First.\n\nSecond."


def test_inline_code_becomes_backticks():
    out = render_statement("<p>Return <code>root</code> now.</p>")
    assert out == "Return `root` now."


def test_strong_becomes_bold():
    assert render_statement("<p><strong>Note:</strong> x</p>") == "**Note:** x"


def test_emphasis_becomes_italics():
    assert render_statement("<p><em>the answer</em></p>") == "*the answer*"


def test_pre_blocks_become_fenced_code():
    out = render_statement("<pre>Input: root = [1]\nOutput: [[1]]\n</pre>")
    assert out == "```\nInput: root = [1]\nOutput: [[1]]\n```"


def test_tags_inside_pre_are_stripped_not_rendered():
    out = render_statement("<pre><strong>Input:</strong> x = 1\n</pre>")
    assert out == "```\nInput: x = 1\n```"


def test_list_items_become_dashes():
    out = render_statement("<ul><li>one</li><li>two</li></ul>")
    assert out == "- one\n- two"


def test_html_entities_are_unescaped():
    assert render_statement("<p>-1000 &lt;= x &lt;= 1000</p>") == "-1000 <= x <= 1000"


def test_nbsp_becomes_a_plain_space():
    assert render_statement("<p>a&nbsp;b</p>") == "a b"


def test_superscript_becomes_caret():
    assert render_statement("<p>10<sup>4</sup></p>") == "10^4"


def test_images_are_kept_as_markdown_references():
    out = render_statement('<p><img alt="tree" src="https://x/y.jpg" /></p>')
    assert out == "![tree](https://x/y.jpg)"


def test_images_without_alt_text_still_render():
    out = render_statement('<p><img src="https://x/y.jpg" /></p>')
    assert out == "![](https://x/y.jpg)"


def test_leading_and_trailing_whitespace_is_trimmed():
    assert render_statement("\n\n<p>  hi  </p>\n\n") == "hi"


def test_empty_input_gives_empty_output():
    assert render_statement("") == ""
```

- [ ] **Step 2: Write the failing visualiser tests**

Create `tests/catalog/test_visualize.py`:

```python
import pytest

from algorhythm.catalog.visualize import (
    render_grid,
    render_linked_list,
    render_tree,
    visualize,
)


def test_empty_tree_says_so():
    assert render_tree([]) == "(empty tree)"


def test_single_node_tree():
    assert render_tree([1]) == "1"


def test_three_node_tree_is_laid_out_exactly():
    assert render_tree([1, 2, 3]) == "  1\n / \\\n2   3"


def test_unbalanced_tree_places_every_value():
    out = render_tree([3, 9, 20, None, None, 15, 7])
    for value in ("3", "9", "20", "15", "7"):
        assert value in out


def test_tree_root_is_on_the_first_line():
    assert render_tree([3, 9, 20, None, None, 15, 7]).splitlines()[0].strip() == "3"


def test_tree_depth_determines_line_count():
    """Depth 3 tree: three value rows plus two connector rows."""
    assert len(render_tree([1, 2, 3, 4, 5, 6, 7]).splitlines()) == 5


def test_tree_handles_negative_and_multidigit_values():
    out = render_tree([100, -50, 250])
    assert "100" in out and "-50" in out and "250" in out


def test_no_line_has_trailing_whitespace():
    for line in render_tree([3, 9, 20, None, None, 15, 7]).splitlines():
        assert line == line.rstrip()


def test_grid_renders_rows_with_spaced_cells():
    assert render_grid([[1, 1, 0], [0, 1, 0]]) == "1 1 0\n0 1 0"


def test_grid_pads_cells_to_equal_width():
    assert render_grid([[1, 10], [100, 2]]) == "  1  10\n100   2"


def test_empty_grid_says_so():
    assert render_grid([]) == "(empty grid)"


def test_linked_list_uses_arrows():
    assert render_linked_list([1, 2, 3]) == "1 -> 2 -> 3 -> null"


def test_empty_linked_list_is_just_null():
    assert render_linked_list([]) == "null"


def test_visualize_dispatches_on_kind():
    assert visualize([1, 2, 3], "tree") == render_tree([1, 2, 3])
    assert visualize([[1]], "grid") == render_grid([[1]])
    assert visualize([1, 2], "linked_list") == render_linked_list([1, 2])


def test_visualize_returns_none_for_raw_values():
    """Nothing structural to draw for a plain int or string."""
    assert visualize(42, "raw") is None


def test_visualize_returns_none_for_unknown_kinds():
    assert visualize([1], "quaternion") is None
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `python -m pytest tests/catalog/test_render.py tests/catalog/test_visualize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.catalog.render'`

- [ ] **Step 4: Implement `algorhythm/catalog/render.py`**

```python
"""LeetCode statement HTML to Markdown.

Uses stdlib `html.parser` rather than a Markdown library, because the
dependency budget is three packages and the input is a narrow, predictable
subset of HTML.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Tags whose open/close both become a paragraph break. `pre` and `br` are
# deliberately absent: each has an explicit branch in both handlers, and
# listing them here would double-emit for the self-closing `<br/>` form,
# which HTMLParser routes through handle_starttag AND handle_endtag.
_BLOCK_TAGS = {"p", "div", "ul", "ol"}


class _StatementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_pre = False
        self._pre_buffer: list[str] = []

    # -- helpers ----------------------------------------------------------

    def _emit(self, text: str) -> None:
        self.parts.append(text)

    # -- HTMLParser hooks -------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "pre":
            self._in_pre = True
            self._pre_buffer = []
        elif self._in_pre:
            return  # tags inside <pre> are decoration; drop them
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "sup":
            self._emit("^")
        elif tag == "li":
            self._emit("\n- ")
        elif tag == "br":
            self._emit("\n")
        elif tag == "img":
            alt = attributes.get("alt") or ""
            src = attributes.get("src") or ""
            self._emit(f"\n\n![{alt}]({src})\n\n")
        elif tag in _BLOCK_TAGS:
            self._emit("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self._in_pre = False
            # Buffered rather than emitted inline: a trailing newline inside
            # <pre> would otherwise put a blank line before the closing fence.
            content = "".join(self._pre_buffer).strip("\n")
            self._emit(f"\n\n```\n{content}\n```\n\n")
        elif self._in_pre:
            return
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag in _BLOCK_TAGS:
            self._emit("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self._pre_buffer.append(data)
        else:
            self._emit(data.replace("\xa0", " "))

    def close(self) -> None:
        # An unclosed <pre> would otherwise discard its whole body silently.
        if self._in_pre:
            self.handle_endtag("pre")
        super().close()


def render_statement(html_text: str) -> str:
    if not html_text:
        return ""

    parser = _StatementParser()
    parser.feed(html_text)
    parser.close()
    text = "".join(parser.parts)

    # Collapse whitespace and blank-line runs, but only OUTSIDE fenced
    # blocks. Doing the blank-line collapse with a global regex over the
    # joined output would silently eat blank lines inside <pre>, undoing the
    # buffering above.
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip() == "```":
            in_fence = not in_fence
            out_lines.append("```")
            continue
        if in_fence:
            out_lines.append(line.rstrip())
            continue
        collapsed = re.sub(r"[ \t]+", " ", line).strip()
        if not collapsed and out_lines and not out_lines[-1]:
            continue  # already have a blank line here
        out_lines.append(collapsed)

    return "\n".join(out_lines).strip()
```

- [ ] **Step 5: Implement `algorhythm/catalog/visualize.py`**

```python
"""ASCII rendering of structural inputs.

Most LeetCode diagrams illustrate data the statement already gives you as a
JSON array, so they can be redrawn from that array — deterministically, and
arguably more legibly in a terminal than the original PNG.

Tree layout uses in-order traversal for horizontal position and depth for
vertical, which is the standard approach and reads correctly for both
balanced and skewed trees.
"""

from __future__ import annotations

from typing import Any

from algorhythm.codecs.leetcode_types import TreeNode, build_tree

# One column between adjacent in-order positions. A gap of 2 pushes the
# three-node tree to columns 0/3/6, which cannot produce the required
#   1\n / \\\n2   3
_COLUMN_GAP = 1


def render_tree(values: list[Any] | None) -> str:
    root = build_tree(values)
    if root is None:
        return "(empty tree)"

    positions: dict[int, tuple[int, int]] = {}
    labels: dict[int, str] = {}
    cursor = 0

    def assign(node: TreeNode, depth: int) -> None:
        nonlocal cursor
        if node.left is not None:
            assign(node.left, depth + 1)
        label = str(node.val)
        labels[id(node)] = label
        positions[id(node)] = (depth * 2, cursor)
        cursor += len(label) + _COLUMN_GAP
        if node.right is not None:
            assign(node.right, depth + 1)

    assign(root, 0)

    height = max(row for row, _ in positions.values()) + 1
    width = max(col + len(labels[key]) for key, (_, col) in positions.items()) + 1
    canvas = [[" "] * width for _ in range(height)]

    def place(row: int, col: int, text: str) -> None:
        for offset, char in enumerate(text):
            if 0 <= row < height and 0 <= col + offset < width:
                canvas[row][col + offset] = char

    def draw(node: TreeNode) -> None:
        row, col = positions[id(node)]
        label = labels[id(node)]
        place(row, col, label)
        if node.left is not None:
            place(row + 1, col - 1, "/")
            draw(node.left)
        if node.right is not None:
            place(row + 1, col + len(label), "\\")
            draw(node.right)

    draw(root)
    return "\n".join("".join(row).rstrip() for row in canvas).rstrip("\n")


def render_grid(rows: list[list[Any]] | None) -> str:
    if not rows:
        return "(empty grid)"
    cells = [[str(value) for value in row] for row in rows]
    width = max((len(cell) for row in cells for cell in row), default=1)
    return "\n".join(" ".join(cell.rjust(width) for cell in row) for row in cells)


def render_linked_list(values: list[Any] | None) -> str:
    if not values:
        return "null"
    return " -> ".join(str(value) for value in values) + " -> null"


def visualize(value: Any, kind: str) -> str | None:
    """Return an ASCII drawing for structural kinds, or None when there is
    nothing worth drawing."""
    if kind == "tree":
        return render_tree(value)
    if kind == "grid":
        return render_grid(value)
    if kind == "linked_list":
        return render_linked_list(value)
    return None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/catalog -v`
Expected: PASS — 54 passed (11 store + 13 fetch + 14 render + 16 visualize)

- [ ] **Step 7: Wire the renderer into the fetcher's default**

The fetcher already accepts a `render` hook and `fetch_question` passes `render_statement`. Verify the whole catalog suite still passes together, then commit.

Run: `python -m pytest tests -v`
Expected: PASS — all tests from Tasks 1-7

- [ ] **Step 8: Commit**

```bash
git add algorhythm/catalog/render.py algorhythm/catalog/visualize.py tests/catalog/
git commit -m "feat(catalog): statement rendering and ASCII visualisers

HTML to Markdown via stdlib html.parser, keeping the dependency budget at
three packages. Trees, grids, and linked lists are redrawn from the JSON
arrays the statement already provides, so most LeetCode diagrams need no
image at all."
```

---

## Task 8: Python test runner

Establishes the result types both runners share, and the batching/timeout strategy. All cases run in **one** subprocess — spawning a fresh interpreter per case costs ~40 ms each and is the difference between a 50 ms run and a 500 ms one. Per-case timeouts come from `SIGALRM` inside that single process, with a whole-batch subprocess timeout as a backstop.

**Files:**
- Create: `algorhythm/runner/__init__.py`
- Create: `algorhythm/runner/harness.py`
- Create: `algorhythm/runner/_pyharness.py`
- Create: `algorhythm/runner/python_runner.py`
- Test: `tests/runner/test_python_runner.py`

**Interfaces:**
- Consumes: `TestCase`, `ParamSpec`, `Problem` from Task 4; `decode`, `encode` from Task 6.
- Produces:
  - `CaseStatus` (str enum: `PASS`/`FAIL`/`ERROR`/`TIMEOUT`)
  - `CaseResult(id, status, expected, actual, error, duration_ms)`
  - `RunResult(cases: list[CaseResult], compile_error: str | None)` with properties `passed: int`, `total: int`, `ok: bool`, `summary: str`
  - `run_python(problem, solution_path, cases, *, timeout_s=5.0) -> RunResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/runner/test_python_runner.py`:

```python
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem, TestCase
from algorhythm.runner.harness import CaseStatus
from algorhythm.runner.python_runner import run_python


def problem(entry_point="addTwo", params=None, return_kind="raw") -> Problem:
    return Problem(
        slug="fixture",
        number=1,
        title="Fixture",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=params or [ParamSpec("a"), ParamSpec("b")],
        return_kind=return_kind,
        entry_point=entry_point,
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


def write(tmp_path, source: str):
    path = tmp_path / "solution.py"
    path.write_text(source)
    return path


CORRECT = """
class Solution:
    def addTwo(self, a, b):
        return a + b
"""

WRONG = """
class Solution:
    def addTwo(self, a, b):
        return a * b
"""

RAISES = """
class Solution:
    def addTwo(self, a, b):
        raise ValueError("boom")
"""

HANGS = """
class Solution:
    def addTwo(self, a, b):
        while True:
            pass
"""

SYNTAX_ERROR = "class Solution:\n    def addTwo(self a b):\n"


def cases():
    return [
        TestCase(id="c1", args={"a": 1, "b": 2}, expected=3, source="example"),
        TestCase(id="c2", args={"a": 10, "b": 5}, expected=15, source="oracle"),
    ]


def test_correct_solution_passes_every_case(tmp_path):
    result = run_python(problem(), write(tmp_path, CORRECT), cases())
    assert result.ok
    assert result.passed == 2
    assert result.total == 2


def test_wrong_solution_reports_each_failure(tmp_path):
    result = run_python(problem(), write(tmp_path, WRONG), cases())
    assert not result.ok
    assert result.passed == 0
    assert all(c.status is CaseStatus.FAIL for c in result.cases)


def test_failure_records_both_expected_and_actual(tmp_path):
    result = run_python(problem(), write(tmp_path, WRONG), cases())
    first = result.cases[0]
    assert first.expected == 3
    assert first.actual == 2


def test_partial_failure_is_reported_per_case(tmp_path):
    source = """
class Solution:
    def addTwo(self, a, b):
        return 3 if a == 1 else 0
"""
    result = run_python(problem(), write(tmp_path, source), cases())
    assert [c.status for c in result.cases] == [CaseStatus.PASS, CaseStatus.FAIL]
    assert result.passed == 1


def test_exception_becomes_an_error_case_not_a_crash(tmp_path):
    result = run_python(problem(), write(tmp_path, RAISES), cases())
    assert all(c.status is CaseStatus.ERROR for c in result.cases)
    assert "boom" in result.cases[0].error


def test_infinite_loop_is_killed_and_reported(tmp_path):
    result = run_python(problem(), write(tmp_path, HANGS), cases(), timeout_s=0.5)
    assert result.cases[0].status is CaseStatus.TIMEOUT


def test_a_hanging_case_does_not_prevent_later_cases_running(tmp_path):
    source = """
class Solution:
    def addTwo(self, a, b):
        if a == 1:
            while True:
                pass
        return a + b
"""
    result = run_python(problem(), write(tmp_path, source), cases(), timeout_s=0.5)
    assert result.cases[0].status is CaseStatus.TIMEOUT
    assert result.cases[1].status is CaseStatus.PASS


def test_syntax_error_surfaces_as_compile_error(tmp_path):
    result = run_python(problem(), write(tmp_path, SYNTAX_ERROR), cases())
    assert result.compile_error is not None
    assert "SyntaxError" in result.compile_error
    assert result.cases == []


def test_missing_entry_point_surfaces_as_compile_error(tmp_path):
    result = run_python(problem(entry_point="nope"), write(tmp_path, CORRECT), cases())
    assert result.compile_error is not None
    assert "nope" in result.compile_error


def test_tree_arguments_are_decoded_before_the_call(tmp_path):
    """The solution must receive a TreeNode, not a list."""
    source = """
class Solution:
    def depth(self, root):
        if root is None:
            return 0
        return 1 + max(self.depth(root.left), self.depth(root.right))
"""
    p = problem(entry_point="depth", params=[ParamSpec("root", "tree")])
    tests = [
        TestCase(
            id="t1",
            args={"root": [3, 9, 20, None, None, 15, 7]},
            expected=3,
            source="example",
        )
    ]
    assert run_python(p, write(tmp_path, source), tests).ok


def test_tree_returns_are_encoded_before_comparison(tmp_path):
    source = """
class Solution:
    def identity(self, root):
        return root
"""
    p = problem(
        entry_point="identity",
        params=[ParamSpec("root", "tree")],
        return_kind="tree",
    )
    tests = [
        TestCase(id="t1", args={"root": [1, 2, 3]}, expected=[1, 2, 3], source="example")
    ]
    assert run_python(p, write(tmp_path, source), tests).ok


def test_empty_case_list_is_a_vacuous_pass(tmp_path):
    result = run_python(problem(), write(tmp_path, CORRECT), [])
    assert result.total == 0
    assert result.ok


def test_summary_reads_as_a_fraction(tmp_path):
    result = run_python(problem(), write(tmp_path, CORRECT), cases())
    assert result.summary.startswith("2/2")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/runner -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.runner'`

- [ ] **Step 3: Implement `algorhythm/runner/harness.py`**

```python
"""Result types shared by both language runners."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class CaseResult:
    id: str
    status: CaseStatus
    expected: Any = None
    actual: Any = None
    error: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True)
class RunResult:
    cases: list[CaseResult] = field(default_factory=list)
    compile_error: str | None = None

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.status is CaseStatus.PASS)

    @property
    def ok(self) -> bool:
        return self.compile_error is None and self.passed == self.total

    @property
    def summary(self) -> str:
        if self.compile_error:
            return "compile error"
        return f"{self.passed}/{self.total} passed"
```

- [ ] **Step 4: Implement `algorhythm/runner/_pyharness.py`**

```python
"""Executed inside the solution subprocess. Reads a job on stdin, writes
one JSON object per case to the file named by `results_path`, flushing
after each.

Two reasons it is a file and not stdout. First, solutions print while
debugging, and a stray `print()` on a shared channel corrupts the
protocol. Second, flushing per case means a batch-timeout kill still
leaves the results of every case that already finished — the caller can
then attribute the hang to the exact case that never reported.

Run as `python -m algorhythm.runner._pyharness` so the package is importable.

Per-case timeouts use SIGALRM, which interrupts Python bytecode. A tight
loop inside a C extension will not be interrupted — the caller's subprocess
timeout is the backstop for that.
"""

from __future__ import annotations

import json
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from algorhythm.codecs.leetcode_types import decode, encode


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):  # noqa: ANN001, ARG001
    raise _Timeout()


def _load_solution(path: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location("_solution", path)
    module = importlib.util.module_from_spec(spec)
    _inject_leetcode_globals(module)
    spec.loader.exec_module(module)
    return module


def _inject_leetcode_globals(module) -> None:
    """LeetCode stubs reference TreeNode, ListNode, Optional and List without
    importing them. Supply them so a pasted stub runs unmodified."""
    from typing import Any as _Any
    from typing import Dict, List, Optional, Set, Tuple

    from algorhythm.codecs.leetcode_types import ListNode, TreeNode

    for name, value in {
        "TreeNode": TreeNode,
        "ListNode": ListNode,
        "Optional": Optional,
        "List": List,
        "Dict": Dict,
        "Set": Set,
        "Tuple": Tuple,
        "Any": _Any,
    }.items():
        setattr(module, name, value)


def main() -> int:
    job = json.load(sys.stdin)
    results_path = job["results_path"]
    solution_path = job["solution_path"]
    entry_point = job["entry_point"]
    params = job["params"]
    return_kind = job["return_kind"]
    timeout_s = float(job["timeout_s"])

    sink = open(results_path, "w", encoding="utf-8")

    def write(payload: dict[str, Any]) -> None:
        json.dump(payload, sink, default=str)
        sink.write("\n")
        sink.flush()

    try:
        module = _load_solution(solution_path)
        solution_cls = getattr(module, "Solution")
        instance = solution_cls()
        method = getattr(instance, entry_point)
    except Exception:
        write({"compile_error": traceback.format_exc(limit=3)})
        sink.close()
        return 0

    signal.signal(signal.SIGALRM, _on_alarm)

    for case in job["cases"]:
        kwargs = {
            spec["name"]: decode(case["args"][spec["name"]], spec["kind"])
            for spec in params
        }
        started = time.perf_counter()
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            raw = method(**kwargs)
            actual = encode(raw, return_kind)
            status = "pass" if actual == case["expected"] else "fail"
            error = None
        except _Timeout:
            status, actual, error = "timeout", None, f"exceeded {timeout_s}s"
        except Exception:
            status, actual, error = "error", None, traceback.format_exc(limit=3)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

        write(
            {
                "id": case["id"],
                "status": status,
                "expected": case["expected"],
                "actual": actual,
                "error": error,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )

    sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Implement `algorhythm/runner/python_runner.py`**

```python
"""Runs a Python solution against its cases in a single subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from algorhythm.catalog.models import Problem, TestCase
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult

# Headroom over the per-case budget so SIGALRM gets a chance to fire first
# and produce a per-case TIMEOUT rather than an opaque whole-batch kill.
_BATCH_OVERHEAD_S = 5.0


def run_python(
    problem: Problem,
    solution_path: Path,
    cases: list[TestCase],
    *,
    timeout_s: float = 5.0,
) -> RunResult:
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as handle:
        results_path = Path(handle.name)

    job = {
        "results_path": str(results_path),
        "solution_path": str(solution_path),
        "entry_point": problem.entry_point,
        "params": [asdict(p) for p in problem.params],
        "return_kind": problem.return_kind,
        "timeout_s": timeout_s,
        "cases": [
            {"id": c.id, "args": c.args, "expected": c.expected} for c in cases
        ],
    }

    batch_timeout = timeout_s * max(len(cases), 1) + _BATCH_OVERHEAD_S
    stderr = ""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "algorhythm.runner._pyharness"],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=batch_timeout,
        )
        stderr = completed.stderr
        crashed = completed.returncode != 0
    except subprocess.TimeoutExpired:
        crashed = False

    try:
        lines = results_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    finally:
        results_path.unlink(missing_ok=True)

    payloads = [json.loads(line) for line in lines if line.strip()]

    for payload in payloads:
        if "compile_error" in payload:
            return RunResult(compile_error=payload["compile_error"])

    if not payloads and crashed:
        return RunResult(compile_error=stderr.strip() or "harness produced no output")

    return _collect(payloads, cases)


def _collect(payloads: list[dict], cases: list[TestCase]) -> RunResult:
    """Pair reported results with the cases that asked for them.

    A case with no result never reported. The FIRST such case is the one
    that hung — the harness flushes in order, so everything after it simply
    never got to run.
    """
    reported = {p["id"]: p for p in payloads}
    results: list[CaseResult] = []
    hang_assigned = False

    for case in cases:
        payload = reported.get(case.id)
        if payload is not None:
            results.append(
                CaseResult(
                    id=payload["id"],
                    status=CaseStatus(payload["status"]),
                    expected=payload["expected"],
                    actual=payload["actual"],
                    error=payload["error"],
                    duration_ms=payload["duration_ms"],
                )
            )
        elif not hang_assigned:
            hang_assigned = True
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.TIMEOUT,
                    expected=case.expected,
                    error="exceeded the batch time budget",
                )
            )
        else:
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.ERROR,
                    expected=case.expected,
                    error="no result reported (an earlier case aborted the run)",
                )
            )

    return RunResult(cases=results)
```

- [ ] **Step 6: Install the package in editable mode so the harness is importable**

```bash
python -m pip install -e ".[dev]"
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
mkdir -p tests/runner && touch algorhythm/runner/__init__.py tests/runner/__init__.py
python -m pytest tests/runner -v
```

Expected: PASS — 13 passed

- [ ] **Step 8: Commit**

```bash
git add algorhythm/runner/ tests/runner/ 
git commit -m "feat(runner): batched Python execution with per-case timeouts

All cases run in one subprocess — a fresh interpreter per case costs ~40ms
each, which is the difference between a 50ms run and a 500ms one. SIGALRM
gives real per-case timeouts inside that process, so one infinite loop does
not cost you the results of every later case."
```

---

## Task 9: C++ runner with compile cache

C++ has no JSON in its standard library, so instead of parsing input at runtime the runner **generates** a `main.cpp` containing the cases as C++ literals. Both sides reduce values to the same canonical string, so comparison is a string equality check and no parser is needed in either direction.

The binary is cached under a content hash of everything that affects it. This is the single biggest latency win in the project: 1-3 seconds becomes ~0 on every re-run.

The harness flushes after each case, so when the whole batch times out the partial stdout tells us exactly which case hung.

**Files:**
- Create: `algorhythm/runner/cpp/leetcode_types.h`
- Create: `algorhythm/runner/cpp_runner.py`
- Test: `tests/runner/test_cpp_runner.py`

**Interfaces:**
- Consumes: `Problem`, `TestCase`, `ParamSpec` from Task 4; `RunResult`, `CaseResult`, `CaseStatus` from Task 8.
- Produces:
  - `run_cpp(problem, solution_path, cases, *, timeout_s=5.0, cache_root=None) -> RunResult`
  - `canonical(value) -> str` — the shared comparison format
  - `CodegenError(Exception)`

- [ ] **Step 1: Write `algorhythm/runner/cpp/leetcode_types.h`**

```cpp
// Types and serialization shared by every generated C++ harness.
// Kept header-only so the generated main.cpp is a single translation unit.
#pragma once

#include <algorithm>
#include <climits>
#include <cmath>
#include <deque>
#include <functional>
#include <iostream>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <sstream>
#include <stack>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace std;

// Sentinel for a null slot in a level-order array literal.
static const int NUL = INT_MIN;

struct TreeNode {
    int val;
    TreeNode *left;
    TreeNode *right;
    TreeNode() : val(0), left(nullptr), right(nullptr) {}
    TreeNode(int x) : val(x), left(nullptr), right(nullptr) {}
    TreeNode(int x, TreeNode *l, TreeNode *r) : val(x), left(l), right(r) {}
};

struct ListNode {
    int val;
    ListNode *next;
    ListNode() : val(0), next(nullptr) {}
    ListNode(int x) : val(x), next(nullptr) {}
    ListNode(int x, ListNode *n) : val(x), next(n) {}
};

inline TreeNode *buildTree(const vector<int> &vals) {
    if (vals.empty() || vals[0] == NUL) return nullptr;
    TreeNode *root = new TreeNode(vals[0]);
    queue<TreeNode *> q;
    q.push(root);
    size_t i = 1;
    while (!q.empty() && i < vals.size()) {
        TreeNode *node = q.front();
        q.pop();
        if (i < vals.size()) {
            int v = vals[i++];
            if (v != NUL) { node->left = new TreeNode(v); q.push(node->left); }
        }
        if (i < vals.size()) {
            int v = vals[i++];
            if (v != NUL) { node->right = new TreeNode(v); q.push(node->right); }
        }
    }
    return root;
}

inline ListNode *buildList(const vector<int> &vals) {
    ListNode head(0);
    ListNode *tail = &head;
    for (int v : vals) { tail->next = new ListNode(v); tail = tail->next; }
    return head.next;
}

// -- canonical serialization ------------------------------------------------
// Must match algorhythm.runner.cpp_runner.canonical() byte for byte.

inline string repr(int v) { return to_string(v); }
inline string repr(long long v) { return to_string(v); }
inline string repr(bool v) { return v ? "true" : "false"; }
inline string repr(char v) { return string("\"") + v + "\""; }

inline string repr(double v) {
    ostringstream os;
    os.precision(5);
    os << fixed << v;
    return os.str();
}

inline string repr(const string &v) { return "\"" + v + "\""; }

template <typename T>
inline string repr(const vector<T> &items) {
    string out = "[";
    for (size_t i = 0; i < items.size(); ++i) {
        if (i) out += ",";
        out += repr(items[i]);
    }
    return out + "]";
}

inline string repr(TreeNode *root) {
    vector<string> out;
    queue<TreeNode *> q;
    q.push(root);
    while (!q.empty()) {
        TreeNode *node = q.front();
        q.pop();
        if (!node) { out.push_back("null"); continue; }
        out.push_back(to_string(node->val));
        q.push(node->left);
        q.push(node->right);
    }
    while (!out.empty() && out.back() == "null") out.pop_back();
    string joined = "[";
    for (size_t i = 0; i < out.size(); ++i) { if (i) joined += ","; joined += out[i]; }
    return joined + "]";
}

inline string repr(ListNode *head) {
    string out = "[";
    bool first = true;
    for (ListNode *n = head; n; n = n->next) {
        if (!first) out += ",";
        out += to_string(n->val);
        first = false;
    }
    return out + "]";
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/runner/test_cpp_runner.py`:

```python
import shutil
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem, TestCase
from algorhythm.runner.cpp_runner import CodegenError, canonical, run_cpp
from algorhythm.runner.harness import CaseStatus

pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None, reason="clang++ not available"
)


def problem(entry_point="addTwo", params=None, return_kind="raw") -> Problem:
    return Problem(
        slug="fixture",
        number=1,
        title="Fixture",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=params or [ParamSpec("a"), ParamSpec("b")],
        return_kind=return_kind,
        entry_point=entry_point,
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


def write(tmp_path, source):
    path = tmp_path / "solution.cpp"
    path.write_text(source)
    return path


CORRECT = """
class Solution {
public:
    int addTwo(int a, int b) { return a + b; }
};
"""

WRONG = """
class Solution {
public:
    int addTwo(int a, int b) { return a * b; }
};
"""

WONT_COMPILE = """
class Solution {
public:
    int addTwo(int a, int b) { return a +; }
};
"""

HANGS = """
class Solution {
public:
    int addTwo(int a, int b) { while (true) {} return 0; }
};
"""


def cases():
    return [
        TestCase(id="c1", args={"a": 1, "b": 2}, expected=3, source="example"),
        TestCase(id="c2", args={"a": 10, "b": 5}, expected=15, source="oracle"),
    ]


# -- canonical form --------------------------------------------------------

def test_canonical_ints():
    assert canonical(5) == "5"
    assert canonical(-3) == "-3"


def test_canonical_bools_are_lowercase():
    assert canonical(True) == "true"
    assert canonical(False) == "false"


def test_canonical_strings_are_quoted():
    assert canonical("ab") == '"ab"'


def test_canonical_lists_have_no_spaces():
    assert canonical([1, 2, 3]) == "[1,2,3]"


def test_canonical_nested_lists():
    assert canonical([[1, 2], [3]]) == "[[1,2],[3]]"


def test_canonical_nulls_in_tree_arrays():
    assert canonical([1, None, 2]) == "[1,null,2]"


def test_canonical_floats_use_fixed_precision():
    assert canonical(1.5) == "1.50000"


# -- execution -------------------------------------------------------------

def test_correct_solution_passes(tmp_path):
    result = run_cpp(problem(), write(tmp_path, CORRECT), cases(), cache_root=tmp_path)
    assert result.ok
    assert result.passed == 2


def test_wrong_solution_fails_with_actual_recorded(tmp_path):
    result = run_cpp(problem(), write(tmp_path, WRONG), cases(), cache_root=tmp_path)
    assert not result.ok
    assert result.cases[0].actual == "2"
    assert result.cases[0].expected == "3"


def test_compile_error_is_surfaced_not_raised(tmp_path):
    result = run_cpp(
        problem(), write(tmp_path, WONT_COMPILE), cases(), cache_root=tmp_path
    )
    assert result.compile_error is not None
    assert result.cases == []


def test_infinite_loop_marks_the_hanging_case(tmp_path):
    result = run_cpp(
        problem(), write(tmp_path, HANGS), cases(), timeout_s=1.0, cache_root=tmp_path
    )
    assert result.cases[0].status is CaseStatus.TIMEOUT


def test_second_run_reuses_the_cached_binary(tmp_path):
    """The whole point of the cache: no compiler invocation the second time."""
    path = write(tmp_path, CORRECT)
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    binaries = list((tmp_path / "cpp").glob("*"))
    mtimes = {b: b.stat().st_mtime_ns for b in binaries}
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    assert {b: b.stat().st_mtime_ns for b in binaries} == mtimes


def test_editing_the_solution_invalidates_the_cache(tmp_path):
    path = write(tmp_path, CORRECT)
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    before = set((tmp_path / "cpp").glob("*"))
    path.write_text(WRONG)
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    assert set((tmp_path / "cpp").glob("*")) != before


def test_vector_arguments_and_returns(tmp_path):
    source = """
class Solution {
public:
    vector<int> doubleAll(vector<int>& nums) {
        vector<int> out;
        for (int n : nums) out.push_back(n * 2);
        return out;
    }
};
"""
    p = problem(entry_point="doubleAll", params=[ParamSpec("nums")])
    tests = [
        TestCase(id="v1", args={"nums": [1, 2, 3]}, expected=[2, 4, 6], source="example")
    ]
    assert run_cpp(p, write(tmp_path, source), tests, cache_root=tmp_path).ok


def test_tree_arguments_are_built_before_the_call(tmp_path):
    source = """
class Solution {
public:
    int depth(TreeNode* root) {
        if (!root) return 0;
        return 1 + max(depth(root->left), depth(root->right));
    }
};
"""
    p = problem(entry_point="depth", params=[ParamSpec("root", "tree")])
    tests = [
        TestCase(
            id="t1",
            args={"root": [3, 9, 20, None, None, 15, 7]},
            expected=3,
            source="example",
        )
    ]
    assert run_cpp(p, write(tmp_path, source), tests, cache_root=tmp_path).ok


def test_string_arguments(tmp_path):
    source = """
class Solution {
public:
    int length(string s) { return (int)s.size(); }
};
"""
    p = problem(entry_point="length", params=[ParamSpec("s")])
    tests = [TestCase(id="s1", args={"s": "hello"}, expected=5, source="example")]
    assert run_cpp(p, write(tmp_path, source), tests, cache_root=tmp_path).ok


def test_unsupported_argument_type_raises_codegen_error(tmp_path):
    p = problem(entry_point="f", params=[ParamSpec("x")])
    tests = [TestCase(id="x", args={"x": {"a": 1}}, expected=1, source="example")]
    with pytest.raises(CodegenError, match="cannot express"):
        run_cpp(p, write(tmp_path, CORRECT), tests, cache_root=tmp_path)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/runner/test_cpp_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.runner.cpp_runner'`

- [ ] **Step 4: Implement `algorhythm/runner/cpp_runner.py`**

```python
"""C++ execution with a content-hashed binary cache.

C++ has no standard JSON, so rather than parsing at runtime we generate a
main.cpp with the cases as C++ literals. Both sides reduce values to the
same canonical string, making comparison a string equality check.

The generated harness flushes after each case, so a whole-batch timeout
still tells us exactly which case hung.
"""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from algorhythm import config
from algorhythm.catalog.models import Problem, TestCase
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult

CXX = "clang++"
CXX_FLAGS = ["-std=c++17", "-O0", "-w"]  # -O0: inputs are tiny, compile speed wins
_TYPES_HEADER = Path(__file__).parent / "cpp" / "leetcode_types.h"

_CPP_TYPE = {
    "tree": "TreeNode*",
    "linked_list": "ListNode*",
}


class CodegenError(Exception):
    pass


def canonical(value: Any) -> str:
    """The comparison format. Must match repr() in leetcode_types.h."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.5f}"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    raise CodegenError(f"cannot express {type(value).__name__} in the canonical form")


def _witness(cases: list[TestCase], name: str) -> Any:
    """A non-empty value for parameter `name` from any case, or None.

    An empty list carries no element type, so `[]` alone cannot tell us
    whether the parameter is `vector<int>`, `vector<string>`, or
    `vector<vector<int>>`. Another case almost always has a populated value
    for the same parameter — the examples do, and the oracle only ever adds
    the empty variant alongside them.
    """
    for case in cases:
        value = case.args.get(name)
        if isinstance(value, list) and value:
            return value
    return None


def _literal(value: Any, kind: str, witness: Any = None) -> tuple[str, str]:
    """Return (c++ declaration type, c++ initializer expression)."""
    if kind in _CPP_TYPE:
        items = ",".join("NUL" if v is None else str(v) for v in (value or []))
        builder = "buildTree" if kind == "tree" else "buildList"
        return _CPP_TYPE[kind], f"{builder}({{{items}}})"

    if isinstance(value, bool):
        return "bool", "true" if value else "false"
    if isinstance(value, int):
        return "int", str(value)
    if isinstance(value, float):
        return "double", repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return "string", f'"{escaped}"'
    if isinstance(value, list):
        if not value:
            # Borrow the element type from a populated case; `vector<int>`
            # is only a last resort and will not compile against a
            # `vector<string>` or `vector<vector<int>>` parameter.
            if witness is not None:
                cpp_type, _ = _literal(witness, kind)
                return cpp_type, "{}"
            return "vector<int>", "{}"
        if all(isinstance(v, list) for v in value):
            rows = ",".join(
                "{" + ",".join(str(x) for x in row) + "}" for row in value
            )
            return "vector<vector<int>>", "{" + rows + "}"
        if all(isinstance(v, str) for v in value):
            items = ",".join(f'"{v}"' for v in value)
            return "vector<string>", "{" + items + "}"
        if all(isinstance(v, bool) for v in value):
            items = ",".join("true" if v else "false" for v in value)
            return "vector<bool>", "{" + items + "}"
        if all(isinstance(v, int) for v in value):
            return "vector<int>", "{" + ",".join(str(v) for v in value) + "}"

    raise CodegenError(f"cannot express {value!r} as a C++ literal")


def _generate_main(problem: Problem, solution_path: Path, cases: list[TestCase]) -> str:
    blocks: list[str] = []
    for index, case in enumerate(cases):
        lines = [f"  {{ // {case.id}"]
        arg_names = []
        for spec in problem.params:
            cpp_type, initializer = _literal(
                case.args[spec.name], spec.kind, _witness(cases, spec.name)
            )
            var = f"arg{index}_{spec.name}"
            lines.append(f"    {cpp_type} {var} = {initializer};")
            arg_names.append(var)
        call = f"solution.{problem.entry_point}({', '.join(arg_names)})"
        expected = canonical(case.expected).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"    string expected = \"{expected}\";")
        lines.append(f"    string actual = repr({call});")
        lines.append(
            f'    cout << "{case.id}\\t" '
            '<< (actual == expected ? "pass" : "fail") '
            '<< "\\t" << actual << "\\n" << flush;'
        )
        lines.append("  }")
        blocks.append("\n".join(lines))

    return "\n".join(
        [
            f'#include "{_TYPES_HEADER}"',
            f'#include "{solution_path}"',
            "",
            "int main() {",
            "  Solution solution;",
            *blocks,
            "  return 0;",
            "}",
            "",
        ]
    )


@lru_cache(maxsize=1)
def _compiler_identity() -> str:
    """The compiler's own version banner, so an upgrade invalidates the cache.

    Hashing the string "clang++" alone would let a stale binary survive a
    toolchain change, which produces bafflingly wrong results.
    """
    try:
        completed = subprocess.run(
            [CXX, "--version"], capture_output=True, text=True, timeout=10
        )
        return completed.stdout
    except (OSError, subprocess.SubprocessError):
        return CXX


def _cache_key(main_source: str) -> str:
    digest = hashlib.sha256()
    digest.update(main_source.encode())
    digest.update(_TYPES_HEADER.read_bytes())
    digest.update(" ".join([CXX, *CXX_FLAGS]).encode())
    digest.update(_compiler_identity().encode())
    return digest.hexdigest()[:16]


def run_cpp(
    problem: Problem,
    solution_path: Path,
    cases: list[TestCase],
    *,
    timeout_s: float = 5.0,
    cache_root: Path | None = None,
) -> RunResult:
    if not cases:
        return RunResult(cases=[])

    root = (cache_root or config.cache_dir()) / "cpp"
    root.mkdir(parents=True, exist_ok=True)

    main_source = _generate_main(problem, solution_path, cases)
    # The solution's own bytes are part of the identity of the binary.
    key = _cache_key(main_source + solution_path.read_text())
    binary = root / key

    if not binary.exists():
        main_path = root / f"{key}.cpp"
        main_path.write_text(main_source)
        compiled = subprocess.run(
            [CXX, *CXX_FLAGS, "-o", str(binary), str(main_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        main_path.unlink(missing_ok=True)
        if compiled.returncode != 0:
            binary.unlink(missing_ok=True)
            return RunResult(compile_error=compiled.stderr.strip())

    batch_timeout = timeout_s * len(cases) + 5.0
    try:
        completed = subprocess.run(
            [str(binary)], capture_output=True, text=True, timeout=batch_timeout
        )
        stdout = completed.stdout
        timed_out = False
    except subprocess.TimeoutExpired as expired:
        raw = expired.output or b""
        stdout = raw.decode() if isinstance(raw, bytes) else raw
        timed_out = True

    return _parse_output(stdout, cases, timed_out)


def _parse_output(
    stdout: str, cases: list[TestCase], timed_out: bool
) -> RunResult:
    reported: dict[str, tuple[str, str]] = {}
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            reported[parts[0]] = (parts[1], parts[2])

    results: list[CaseResult] = []
    hang_assigned = False
    for case in cases:
        expected = canonical(case.expected)
        if case.id in reported:
            status_text, actual = reported[case.id]
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus(status_text),
                    expected=expected,
                    actual=actual,
                )
            )
            continue

        # Unreported. The first unreported case is the one that hung; any
        # after it never got the chance to run.
        if timed_out and not hang_assigned:
            hang_assigned = True
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.TIMEOUT,
                    expected=expected,
                    error="exceeded the time budget",
                )
            )
        else:
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.ERROR,
                    expected=expected,
                    error="no result reported (earlier case aborted the run)",
                )
            )

    return RunResult(cases=results)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/runner -v`
Expected: PASS — 13 Python runner tests plus 17 C++ tests (skipped if `clang++` is absent)

- [ ] **Step 6: Commit**

```bash
git add algorhythm/runner/cpp/ algorhythm/runner/cpp_runner.py tests/runner/test_cpp_runner.py
git commit -m "feat(runner): C++ execution with content-hashed compile cache

Generates main.cpp with cases as C++ literals rather than parsing JSON at
runtime, so neither side needs a parser. Caching the binary under a hash of
the solution, harness, and flags turns a 1-3s compile into ~0ms on re-runs
— the largest single latency win in the project."
```

---

## Task 10: Oracle-derived edge cases

Generates edge-case inputs by perturbing the example inputs one parameter at a time, then derives the expected outputs by running the **reference** solution. No hand-authored expectations, and no combinatorial explosion.

**Files:**
- Create: `algorhythm/oracle.py`
- Modify: `algorhythm/runner/python_runner.py` — add `evaluate_python`
- Test: `tests/test_oracle.py`

**Interfaces:**
- Consumes: `Problem`, `ParamSpec`, `TestCase` from Task 4; `run_python`, `RunResult`, `CaseStatus` from Task 8.
- Produces:
  - `evaluate_python(problem, solution_path, arg_sets, *, timeout_s=5.0) -> RunResult` (in `python_runner`)
  - `perturbations(value, kind) -> list` — edge variants of a single argument
  - `candidate_args(problem, seed_args) -> list[dict]`
  - `generate_oracle_cases(problem, reference_path, seed_args, *, timeout_s=5.0) -> list[TestCase]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_oracle.py`:

```python
from datetime import datetime, timezone

from algorhythm.catalog.models import ParamSpec, Problem
from algorhythm.oracle import candidate_args, generate_oracle_cases, perturbations


def problem(entry_point="total", params=None, return_kind="raw") -> Problem:
    return Problem(
        slug="fixture",
        number=1,
        title="Fixture",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=params or [ParamSpec("nums")],
        return_kind=return_kind,
        entry_point=entry_point,
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


REFERENCE = """
class Solution:
    def total(self, nums):
        return sum(nums)
"""

REFERENCE_TWO_ARGS = """
class Solution:
    def total(self, nums, k):
        return sum(nums) * k
"""


# -- perturbation ---------------------------------------------------------

def test_int_list_perturbations_include_empty_and_singleton():
    variants = perturbations([1, 2, 3], "raw")
    assert [] in variants
    assert any(len(v) == 1 for v in variants)


def test_int_list_perturbations_include_duplicates():
    variants = perturbations([1, 2, 3], "raw")
    assert any(len(set(v)) == 1 and len(v) > 1 for v in variants)


def test_int_list_perturbations_include_negatives():
    variants = perturbations([1, 2, 3], "raw")
    assert any(any(x < 0 for x in v) for v in variants)


def test_string_perturbations_include_empty_and_single_char():
    variants = perturbations("hello", "raw")
    assert "" in variants
    assert any(len(v) == 1 for v in variants)


def test_int_perturbations_span_zero_and_negative():
    variants = perturbations(5, "raw")
    assert 0 in variants
    assert any(v < 0 for v in variants)


def test_tree_perturbations_include_empty_and_single_node():
    variants = perturbations([3, 9, 20, None, None, 15, 7], "tree")
    assert [] in variants
    assert [1] in variants


def test_tree_perturbations_include_a_skewed_chain():
    """Skewed trees are where naive index-arithmetic solutions break."""
    variants = perturbations([1, 2, 3], "tree")
    assert any(None in v for v in variants if isinstance(v, list) and len(v) > 2)


def test_linked_list_perturbations_include_empty_and_single():
    variants = perturbations([1, 2, 3], "linked_list")
    assert [] in variants
    assert [1] in variants


def test_grid_perturbations_include_single_cell():
    variants = perturbations([[1, 0], [0, 1]], "grid")
    assert [[1]] in variants


def test_perturbations_never_include_the_original():
    assert [1, 2, 3] not in perturbations([1, 2, 3], "raw")


# -- candidate assembly ---------------------------------------------------

def test_candidates_vary_one_parameter_at_a_time():
    """Cartesian product would explode; one-at-a-time keeps it linear."""
    p = problem(params=[ParamSpec("nums"), ParamSpec("k")])
    seed = {"nums": [1, 2, 3], "k": 2}
    candidates = candidate_args(p, seed)
    for candidate in candidates:
        differing = [name for name in seed if candidate[name] != seed[name]]
        assert len(differing) == 1


def test_candidates_are_deduplicated():
    p = problem(params=[ParamSpec("nums")])
    candidates = candidate_args(p, {"nums": [1, 2, 3]})
    seen = [tuple(sorted(c.items(), key=str)) for c in candidates]
    assert len(seen) == len(set(seen))


# -- generation -----------------------------------------------------------

def test_generated_cases_take_expectations_from_the_reference(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE)
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert cases
    for case in cases:
        assert case.expected == sum(case.args["nums"])


def test_generated_cases_are_tagged_as_oracle(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE)
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert all(c.source == "oracle" for c in cases)


def test_generated_case_ids_are_unique(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE)
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert len({c.id for c in cases}) == len(cases)


def test_inputs_the_reference_rejects_are_dropped(tmp_path):
    """A reference that raises on empty input means empty is out of contract,
    so that candidate must not become a test case."""
    reference = tmp_path / "reference.py"
    reference.write_text(
        """
class Solution:
    def total(self, nums):
        if not nums:
            raise ValueError("out of contract")
        return sum(nums)
"""
    )
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert all(c.args["nums"] != [] for c in cases)


def test_multi_parameter_problems_work(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE_TWO_ARGS)
    p = problem(params=[ParamSpec("nums"), ParamSpec("k")])
    cases = generate_oracle_cases(p, reference, {"nums": [1, 2], "k": 3})
    assert cases
    for case in cases:
        assert case.expected == sum(case.args["nums"]) * case.args["k"]


def test_a_broken_reference_yields_no_cases_rather_than_raising(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text("class Solution:\n    def total(self nums):\n")
    assert generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]}) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_oracle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.oracle'`

- [ ] **Step 3: Add `evaluate_python` to `algorhythm/runner/python_runner.py`**

Append to the module:

```python
# A value no real solution can return, so every probe reports FAIL and we
# read `actual` as the reference's output.
_ORACLE_SENTINEL = "__algorhythm_oracle_probe__"


def evaluate_python(
    problem: Problem,
    solution_path: Path,
    arg_sets: list[dict],
    *,
    timeout_s: float = 5.0,
) -> RunResult:
    """Run a solution over argument sets purely to observe its outputs.

    Used to derive expected values from a reference solution. Read
    `case.actual`; `case.status` is FAIL by construction and carries no
    meaning here beyond 'it ran'.
    """
    cases = [
        TestCase(
            id=f"probe-{index}",
            args=args,
            expected=_ORACLE_SENTINEL,
            source="oracle",
        )
        for index, args in enumerate(arg_sets)
    ]
    return run_python(problem, solution_path, cases, timeout_s=timeout_s)
```

- [ ] **Step 4: Implement `algorhythm/oracle.py`**

```python
"""Edge-case generation using the reference solution as an oracle.

Two ideas do the work here:

  1. Perturb the *example* input rather than inventing inputs from nothing.
     The example is known to be in-contract, so variations of it usually are
     too, and its shape tells us what the parameter actually is.

  2. Vary one parameter at a time. A cartesian product over parameters
     explodes; one-at-a-time stays linear and still covers each parameter's
     edges.

Any candidate the reference rejects — by raising or hanging — is dropped
rather than recorded, on the reasoning that it is out of contract.
"""

from __future__ import annotations

import json
from itertools import zip_longest
from pathlib import Path
from typing import Any

from algorhythm.catalog.models import Problem, TestCase
from algorhythm.runner.harness import CaseStatus
from algorhythm.runner.python_runner import evaluate_python

# Cases kept per problem, and how many candidates we're willing to run
# through the reference to find them. The pool is larger because the
# reference rejects out-of-contract candidates, and they all run in one
# batched subprocess, so a wider pool costs almost nothing.
_MAX_CASES = 8
_MAX_CANDIDATES = 24


def _int_list_perturbations(value: list[int]) -> list[list[int]]:
    first = value[0] if value else 0
    return [
        [],
        [first],
        [first] * 3,
        sorted(value),
        list(reversed(value)),
        [-abs(v) for v in value],
        value + value,
    ]


def perturbations(value: Any, kind: str) -> list[Any]:
    """Edge variants of a single argument. Never includes `value` itself."""
    if kind == "tree":
        return [[], [1], [1, 2, None, 3], [1, None, 2, None, 3]]
    if kind == "linked_list":
        return [[], [1], [1, 1, 1]]
    if kind == "grid":
        return [[[1]], [[0]], [row[:1] for row in (value or [[0]])]]

    if isinstance(value, bool):
        return [not value]
    if isinstance(value, int):
        return [0, 1, -1, -abs(value) if value else -1]
    if isinstance(value, str):
        first = value[0] if value else "a"
        return ["", first, first * 3, value[::-1]]
    if isinstance(value, list):
        if value and all(isinstance(v, list) for v in value):
            return [[[1]], [value[0]]]
        if all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            return _int_list_perturbations(value)
        if all(isinstance(v, str) for v in value):
            return [[], value[:1], value + value]
    return []


def _key(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, default=str)


def candidate_args(problem: Problem, seed_args: dict[str, Any]) -> list[dict[str, Any]]:
    """Argument sets that differ from `seed_args` in exactly one parameter.

    Round-robins across parameters rather than exhausting each in turn: the
    caller truncates this list, and parameter-major order would let the
    first parameter's variants consume the whole budget, leaving later
    parameters with no coverage at all.
    """
    per_parameter: list[list[dict[str, Any]]] = []
    for spec in problem.params:
        if spec.name not in seed_args:
            continue
        variants = []
        for variant in perturbations(seed_args[spec.name], spec.kind):
            candidate = dict(seed_args)
            candidate[spec.name] = variant
            variants.append(candidate)
        per_parameter.append(variants)

    out: list[dict[str, Any]] = []
    seen = {_key(seed_args)}
    for row in zip_longest(*per_parameter):
        for candidate in row:
            if candidate is None:
                continue
            fingerprint = _key(candidate)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            out.append(candidate)

    return out


def generate_oracle_cases(
    problem: Problem,
    reference_path: Path,
    seed_args: dict[str, Any],
    *,
    timeout_s: float = 5.0,
) -> list[TestCase]:
    """Derive test cases whose expected outputs come from the reference.

    Returns an empty list if the reference will not run — a broken reference
    must never silently produce authoritative-looking expectations.
    """
    candidates = candidate_args(problem, seed_args)[:_MAX_CANDIDATES]
    if not candidates:
        return []

    result = evaluate_python(problem, reference_path, candidates, timeout_s=timeout_s)
    if result.compile_error:
        return []

    # Keep the first _MAX_CASES survivors rather than truncating the pool
    # up front: candidates the reference rejects must not consume the budget,
    # or a problem whose early candidates are all out of contract ends up
    # with no generated cases at all.
    cases: list[TestCase] = []
    for case_result, args in zip(result.cases, candidates):
        if len(cases) >= _MAX_CASES:
            break
        if case_result.status in (CaseStatus.ERROR, CaseStatus.TIMEOUT):
            continue  # out of contract for this problem
        cases.append(
            TestCase(
                id=f"oracle-{len(cases) + 1}",
                args=args,
                expected=case_result.actual,
                source="oracle",
            )
        )
    return cases
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_oracle.py -v`
Expected: PASS — 18 passed

- [ ] **Step 6: Commit**

```bash
git add algorhythm/oracle.py algorhythm/runner/python_runner.py tests/test_oracle.py
git commit -m "feat(oracle): derive edge cases from the reference solution

Perturbs the example input one parameter at a time — a cartesian product
over parameters explodes, one-at-a-time stays linear. Candidates the
reference rejects are dropped as out of contract, and a reference that
will not run yields nothing rather than authoritative-looking garbage."
```

---

## Task 11: Reviewer

**Files:**
- Create: `algorhythm/reviewer/__init__.py`
- Create: `algorhythm/reviewer/protocol.py`
- Create: `algorhythm/reviewer/prompt.py`
- Create: `algorhythm/reviewer/ollama.py`
- Test: `tests/reviewer/test_prompt.py`
- Test: `tests/reviewer/test_ollama.py`

**Interfaces:**
- Consumes: `Problem` from Task 4; `RunResult`, `CaseStatus` from Task 8; `Grade` from Task 1.
- Produces:
  - `ReviewRequest(problem, language, solution_source, reference_source, run_result)`
  - `Review(text, proposed_grade: Grade | None, grade_reason: str | None, model: str | None)`
  - `Reviewer` Protocol with `review(request) -> Review`
  - `ReviewerUnavailable(Exception)`
  - `SYSTEM_PROMPT: str`, `build_prompt(request) -> str`, `RESPONSE_SCHEMA: dict`
  - `OllamaReviewer(model="qwen2.5-coder:7b", host="http://localhost:11434", client=None)`

- [ ] **Step 1: Write the failing prompt tests**

Create `tests/reviewer/test_prompt.py`:

```python
from datetime import datetime, timezone

from algorhythm.catalog.models import ParamSpec, Problem
from algorhythm.reviewer.prompt import SYSTEM_PROMPT, build_prompt
from algorhythm.reviewer.protocol import ReviewRequest
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult


def problem() -> Problem:
    return Problem(
        slug="two-sum",
        number=1,
        title="Two Sum",
        difficulty="Easy",
        topics=["Array", "Hash Table"],
        companies=[],
        url="https://leetcode.com/problems/two-sum/",
        statement_md="Return indices of the two numbers that add to target.",
        constraints=["2 <= nums.length <= 10^4"],
        examples=[],
        params=[ParamSpec("nums"), ParamSpec("target")],
        return_kind="raw",
        entry_point="twoSum",
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


def request(run_result=None) -> ReviewRequest:
    return ReviewRequest(
        problem=problem(),
        language="python",
        solution_source="class Solution:\n    def twoSum(self, nums, target): ...",
        reference_source="# reference: hash map, O(n)",
        run_result=run_result or RunResult(cases=[]),
    )


def test_prompt_includes_the_problem_title_and_statement():
    text = build_prompt(request())
    assert "Two Sum" in text
    assert "Return indices" in text


def test_prompt_includes_the_reference_solution():
    """Grounding is what makes a 7B model viable here — without the
    reference this becomes a recall task it will fail."""
    assert "hash map, O(n)" in build_prompt(request())


def test_prompt_includes_the_submitted_solution():
    assert "def twoSum" in build_prompt(request())


def test_prompt_states_the_language():
    assert "python" in build_prompt(request()).lower()


def test_prompt_reports_a_clean_test_run():
    run = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.PASS)])
    assert "1/1 passed" in build_prompt(request(run))


def test_prompt_names_failing_cases_with_inputs():
    run = RunResult(
        cases=[
            CaseResult(
                id="oracle-2",
                status=CaseStatus.FAIL,
                expected=[0, 1],
                actual=[1, 0],
            )
        ]
    )
    text = build_prompt(request(run))
    assert "oracle-2" in text
    assert "[0, 1]" in text
    assert "[1, 0]" in text


def test_prompt_reports_a_compile_error():
    run = RunResult(compile_error="SyntaxError: invalid syntax")
    assert "SyntaxError" in build_prompt(request(run))


def test_prompt_flags_a_missing_reference_explicitly():
    """The review must say so rather than silently inventing a comparison."""
    req = ReviewRequest(
        problem=problem(),
        language="python",
        solution_source="x",
        reference_source=None,
        run_result=RunResult(cases=[]),
    )
    assert "no reference solution" in build_prompt(req).lower()


def test_system_prompt_asks_for_prose_not_a_rubric():
    assert "rubric" not in SYSTEM_PROMPT.lower()
    assert "again" in SYSTEM_PROMPT and "easy" in SYSTEM_PROMPT


def test_system_prompt_is_long_enough_to_be_cacheable():
    """Opus-style prompt caching needs a stable prefix of real size; more
    importantly a short prompt underspecifies the task for a 7B model."""
    assert len(SYSTEM_PROMPT) > 400
```

- [ ] **Step 2: Write the failing Ollama tests**

Create `tests/reviewer/test_ollama.py`:

```python
import json

import httpx
import pytest

from algorhythm.reviewer.ollama import OllamaReviewer
from algorhythm.reviewer.protocol import Review, ReviewerUnavailable
from algorhythm.scheduler.sm2 import Grade
from tests.reviewer.test_prompt import request


def transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_response(payload: dict):
    def handler(_request):
        return httpx.Response(200, json={"response": json.dumps(payload)})

    return handler


def test_parses_a_well_formed_response():
    client = transport(
        ok_response(
            {
                "review": "You used sorting; the intended approach is a hash map.",
                "proposed_grade": "hard",
                "grade_reason": "Correct but not the intended pattern.",
            }
        )
    )
    review = OllamaReviewer(client=client).review(request())
    assert isinstance(review, Review)
    assert review.proposed_grade is Grade.HARD
    assert "hash map" in review.text
    assert review.grade_reason.startswith("Correct")


def test_records_the_model_name():
    client = transport(ok_response({"review": "x", "proposed_grade": "good"}))
    review = OllamaReviewer(model="qwen2.5-coder:7b", client=client).review(request())
    assert review.model == "qwen2.5-coder:7b"


def test_sends_the_configured_model_and_a_json_schema():
    captured = {}

    def handler(req):
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={"response": json.dumps({"review": "x"})})

    OllamaReviewer(model="custom:1b", client=transport(handler)).review(request())
    assert captured["model"] == "custom:1b"
    assert captured["stream"] is False
    assert captured["format"]["type"] == "object"


def test_connection_failure_raises_reviewer_unavailable():
    def handler(_request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ReviewerUnavailable, match="Ollama"):
        OllamaReviewer(client=transport(handler)).review(request())


def test_http_error_raises_reviewer_unavailable():
    def handler(_request):
        return httpx.Response(500, text="internal error")

    with pytest.raises(ReviewerUnavailable):
        OllamaReviewer(client=transport(handler)).review(request())


def test_non_json_body_is_returned_as_raw_text_without_a_grade():
    """Nothing may block the loop — a malformed review still shows, the
    user just grades it themselves."""

    def handler(_request):
        return httpx.Response(200, json={"response": "I think it looks fine!"})

    review = OllamaReviewer(client=transport(handler)).review(request())
    assert review.proposed_grade is None
    assert "looks fine" in review.text


def test_unrecognised_grade_is_discarded_but_text_is_kept():
    client = transport(
        ok_response({"review": "solid", "proposed_grade": "excellent"})
    )
    review = OllamaReviewer(client=client).review(request())
    assert review.proposed_grade is None
    assert review.text == "solid"


def test_missing_review_field_falls_back_to_the_raw_body():
    client = transport(ok_response({"proposed_grade": "good"}))
    review = OllamaReviewer(client=client).review(request())
    assert review.proposed_grade is Grade.GOOD
    assert review.text != ""
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `python -m pytest tests/reviewer -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.reviewer'`

- [ ] **Step 4: Implement `algorhythm/reviewer/protocol.py`**

```python
"""The swap seam. Everything downstream depends on `Reviewer`, not on
Ollama, so replacing the model — or adding the v2 hint agent — is a new
implementation rather than a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from algorhythm.catalog.models import Problem
from algorhythm.runner.harness import RunResult
from algorhythm.scheduler.sm2 import Grade


class ReviewerUnavailable(Exception):
    """The reviewer could not be reached. Callers must degrade gracefully:
    the rep still finishes and the user grades it manually."""


@dataclass(frozen=True)
class ReviewRequest:
    problem: Problem
    language: str
    solution_source: str
    reference_source: str | None
    run_result: RunResult


@dataclass(frozen=True)
class Review:
    text: str
    proposed_grade: Grade | None = None
    grade_reason: str | None = None
    model: str | None = None


class Reviewer(Protocol):
    def review(self, request: ReviewRequest) -> Review: ...
```

- [ ] **Step 5: Implement `algorhythm/reviewer/prompt.py`**

```python
"""Prompt construction.

The reference solution and concrete test results are the whole reason a 7B
model can do this job. Without them the model is being asked to recall the
optimal approach for a specific problem, which is exactly what small models
are worst at. With them it is comparing two pieces of code, which is a much
easier task.
"""

from __future__ import annotations

from algorhythm.reviewer.protocol import ReviewRequest
from algorhythm.runner.harness import CaseStatus, RunResult

SYSTEM_PROMPT = """You are a technical interview coach reviewing a candidate's \
solution to a data-structures problem. You are given the problem, a known-good \
reference solution, the candidate's submission, and the results of running it \
against a local test suite.

Your job is to tell the candidate how far their solution is from the recommended \
one. Focus on the gap that matters most for interview performance: whether they \
reached for the right technique. If they used a different approach than the \
reference, say what the reference does and why it is preferred. Mention time and \
space complexity when the two solutions differ on it. Mention edge cases only when \
a test actually failed on one.

Write plain prose, a short paragraph or two. Do not use headings or bullet lists. \
Do not restate the problem. Do not praise generically.

The test results are authoritative for correctness — do not claim the code is \
wrong when the tests passed, or right when they failed.

Finish by proposing a spaced-repetition grade:
  again - could not solve it, or the approach was fundamentally wrong
  hard  - solved it, but with the wrong technique or notably worse complexity
  good  - essentially the reference approach, with minor differences
  easy  - clean, direct, and equivalent to the reference with no fumbling
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "review": {"type": "string"},
        "proposed_grade": {
            "type": "string",
            "enum": ["again", "hard", "good", "easy"],
        },
        "grade_reason": {"type": "string"},
    },
    "required": ["review", "proposed_grade"],
}


def _last_line(error: str | None) -> str:
    """The final meaningful line of a traceback.

    `splitlines()[-1:]` would be a list slice, rendering the literal
    `['ValueError: bad']` into the prompt instead of the message itself.
    """
    lines = [line for line in (error or "").strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no detail available"


def _format_results(result: RunResult) -> str:
    if result.compile_error:
        return f"The submission did not compile or import:\n{result.compile_error}"
    if result.total == 0:
        return "No tests were run."

    lines = [f"Tests: {result.summary}"]
    for case in result.cases:
        if case.status is CaseStatus.PASS:
            continue
        detail = {
            CaseStatus.FAIL: f"expected {case.expected!r}, got {case.actual!r}",
            CaseStatus.ERROR: f"raised: {_last_line(case.error)}",
            CaseStatus.TIMEOUT: "timed out",
        }.get(case.status, case.status.value)
        lines.append(f"  - {case.id}: {case.status.value} ({detail})")
    return "\n".join(lines)


def build_prompt(request: ReviewRequest) -> str:
    problem = request.problem
    reference = (
        request.reference_source
        or "(no reference solution is available for this problem — say so in your "
        "review, and do not invent a comparison)"
    )

    constraints = "\n".join(f"- {c}" for c in problem.constraints) or "(none recorded)"

    return f"""## Problem

{problem.number}. {problem.title} ({problem.difficulty})
Topics: {', '.join(problem.topics) or 'none recorded'}

{problem.statement_md}

Constraints:
{constraints}

## Reference solution ({request.language})

```{request.language}
{reference}
```

## Candidate's submission ({request.language})

```{request.language}
{request.solution_source}
```

## Test results

{_format_results(request.run_result)}
"""
```

- [ ] **Step 6: Implement `algorhythm/reviewer/ollama.py`**

```python
"""Ollama-backed reviewer.

One HTTP POST. Ollama's `format` parameter takes a JSON schema, so the
response arrives structured and no output-parsing layer is needed.

Every parse failure degrades rather than raises: a malformed review is
still shown, the user just grades it themselves. Only an unreachable
service raises, and callers catch that to skip review entirely.
"""

from __future__ import annotations

import json

import httpx

from algorhythm.reviewer.prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT, build_prompt
from algorhythm.reviewer.protocol import Review, ReviewerUnavailable, ReviewRequest
from algorhythm.scheduler.sm2 import Grade

DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_HOST = "http://localhost:11434"


class OllamaReviewer:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        client: httpx.Client | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self._client = client
        self._timeout_s = timeout_s

    def review(self, request: ReviewRequest) -> Review:
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": build_prompt(request),
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "options": {"temperature": 0.2},
        }

        client = self._client or httpx.Client(timeout=self._timeout_s)
        owns_client = self._client is None
        try:
            response = client.post(f"{self.host}/api/generate", json=payload)
            response.raise_for_status()
            raw_body = response.text
        except httpx.HTTPError as exc:
            raise ReviewerUnavailable(
                f"Ollama at {self.host} could not be reached or returned an "
                f"error: {exc}. Start it with `ollama serve`, or grade this "
                "rep yourself."
            ) from exc
        finally:
            if owns_client:
                client.close()

        # Reachable but malformed. Degrade rather than raise: only an
        # unreachable service may stop a rep, and a JSONDecodeError or an
        # AttributeError escaping here would crash a caller that has no
        # reason to catch either.
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return Review(text=raw_body.strip(), model=self.model)

        if not isinstance(body, dict):
            return Review(text=raw_body.strip(), model=self.model)

        return self._to_review(body.get("response", ""))

    def _to_review(self, raw: str) -> Review:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            return Review(text=raw.strip(), model=self.model)

        try:
            grade = Grade(parsed.get("proposed_grade"))
        except ValueError:
            grade = None

        return Review(
            text=str(parsed.get("review") or raw).strip(),
            proposed_grade=grade,
            grade_reason=parsed.get("grade_reason"),
            model=self.model,
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
mkdir -p tests/reviewer && touch algorhythm/reviewer/__init__.py tests/reviewer/__init__.py
python -m pytest tests/reviewer -v
```

Expected: PASS — 18 passed

- [ ] **Step 8: Commit**

```bash
git add algorhythm/reviewer/ tests/reviewer/
git commit -m "feat(reviewer): Ollama reviewer behind a Protocol seam

Ollama's format parameter takes a JSON schema, so structured output arrives
without a parsing layer. Every parse failure degrades to raw text rather
than raising — only an unreachable service raises, so a review can always
be skipped without blocking the rep."
```

---

## Task 12: nvim workspace and editor session

**Files:**
- Create: `algorhythm/editor/__init__.py`
- Create: `algorhythm/editor/session.py`
- Create: `algorhythm/editor/lua/algorhythm.lua`
- Test: `tests/editor/test_session.py`

**Interfaces:**
- Consumes: `Problem` from Task 4; `visualize` from Task 7.
- Produces:
  - `Workspace(dir, statement_path, solution_path, results_path, review_path, meta_path, language, slug)`
  - `prepare_workspace(problem, language, *, stub, previous_attempt=None, root=None) -> Workspace`
  - `nvim_command(workspace) -> list[str]`
  - `launch(workspace, *, runner=subprocess.run) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/editor/test_session.py`:

```python
import json
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Example, ParamSpec, Problem
from algorhythm.editor.session import launch, nvim_command, prepare_workspace


def problem() -> Problem:
    return Problem(
        slug="binary-tree-level-order-traversal",
        number=102,
        title="Binary Tree Level Order Traversal",
        difficulty="Medium",
        topics=["Tree"],
        companies=["Amazon"],
        url="https://leetcode.com/problems/binary-tree-level-order-traversal/",
        statement_md="Return the level order traversal.",
        constraints=["0 <= nodes <= 2000"],
        examples=[
            Example(
                input_text="root = [3,9,20,null,null,15,7]",
                output_text="[[3],[9,20],[15,7]]",
                explanation=None,
            )
        ],
        params=[ParamSpec("root", "tree")],
        return_kind="raw",
        entry_point="levelOrder",
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


STUB = "class Solution:\n    def levelOrder(self, root):\n        "


def test_workspace_files_are_created(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert ws.statement_path.exists()
    assert ws.solution_path.exists()
    assert ws.meta_path.exists()


def test_solution_file_uses_the_language_extension(tmp_path):
    py = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    cpp = prepare_workspace(problem(), "cpp", stub="// stub", root=tmp_path)
    assert py.solution_path.name == "solution.py"
    assert cpp.solution_path.name == "solution.cpp"


def test_solution_is_seeded_with_the_stub(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert ws.solution_path.read_text() == STUB


def test_previous_attempt_takes_precedence_over_the_stub(tmp_path):
    previous = "class Solution:\n    def levelOrder(self, root):\n        return []"
    ws = prepare_workspace(
        problem(), "python", stub=STUB, previous_attempt=previous, root=tmp_path
    )
    assert ws.solution_path.read_text() == previous


def test_statement_includes_the_title_and_difficulty(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "102. Binary Tree Level Order Traversal" in text
    assert "Medium" in text


def test_statement_includes_topics_and_companies(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "Tree" in text
    assert "Amazon" in text


def test_statement_includes_examples_and_constraints(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "root = [3,9,20,null,null,15,7]" in text
    assert "0 <= nodes <= 2000" in text


def test_statement_renders_tree_examples_as_ascii(tmp_path):
    """The whole point of the visualiser — a tree example should be drawn,
    not just printed as an array."""
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "/" in text and "\\" in text


def test_meta_records_what_the_editor_hooks_need(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    meta = json.loads(ws.meta_path.read_text())
    assert meta["slug"] == "binary-tree-level-order-traversal"
    assert meta["language"] == "python"


def test_results_and_review_files_start_empty_but_present(tmp_path):
    """nvim opens them as splits, so they must exist before launch."""
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert ws.results_path.exists()
    assert ws.review_path.exists()


def test_each_workspace_is_isolated(tmp_path):
    first = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    second = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert first.dir != second.dir


def test_nvim_command_sources_the_lua_module(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    command = nvim_command(ws)
    assert command[0] == "nvim"
    assert any("algorhythm.lua" in part for part in command)


def test_nvim_command_opens_the_solution_file(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert str(ws.solution_path) in nvim_command(ws)


def test_launch_returns_the_editor_exit_code(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    calls = []

    class Result:
        returncode = 0

    def fake_runner(command, **kwargs):
        calls.append(command)
        return Result()

    assert launch(ws, runner=fake_runner) == 0
    assert calls and calls[0][0] == "nvim"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/editor -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.editor'`

- [ ] **Step 3: Implement `algorhythm/editor/session.py`**

```python
"""Scratch workspace preparation and nvim launch.

Each rep gets its own directory so nothing leaks between problems and an
abandoned rep leaves no trace in the database.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from algorhythm.catalog.models import LANGUAGES, Problem
from algorhythm.catalog.visualize import visualize

_LUA_MODULE = Path(__file__).parent / "lua" / "algorhythm.lua"


@dataclass(frozen=True)
class Workspace:
    dir: Path
    statement_path: Path
    solution_path: Path
    results_path: Path
    review_path: Path
    meta_path: Path
    language: str
    slug: str


def _render_statement(problem: Problem) -> str:
    lines = [
        f"# {problem.number}. {problem.title}",
        "",
        f"**{problem.difficulty}** · {' · '.join(problem.topics) or 'untagged'}",
    ]
    if problem.companies:
        lines.append(f"Asked at: {', '.join(problem.companies)}")
    lines += ["", problem.statement_md, ""]

    for index, example in enumerate(problem.examples, start=1):
        lines.append(f"## Example {index}")
        drawing = _drawing_for(problem, example.input_text)
        if drawing:
            lines += ["", "```", drawing, "```"]
        lines += [
            "",
            f"Input:  {example.input_text}",
            f"Output: {example.output_text}",
        ]
        if example.explanation:
            lines.append(f"Explain: {example.explanation}")
        lines.append("")

    if problem.constraints:
        lines.append("## Constraints")
        lines += [f"- {c}" for c in problem.constraints]
        lines.append("")

    lines.append(f"<{problem.url}>")
    return "\n".join(lines)


def _drawing_for(problem: Problem, input_text: str) -> str | None:
    """Draw the first structural parameter found in the example input."""
    for spec in problem.params:
        if spec.kind == "raw":
            continue
        marker = f"{spec.name} = "
        if marker not in input_text:
            continue
        fragment = input_text.split(marker, 1)[1].lstrip()
        try:
            # raw_decode consumes exactly one JSON value and reports where it
            # ended, so a trailing `, target = 9` is ignored and an array
            # containing `, ` (LeetCode writes `[1, 2, 3]`) stays intact.
            # Splitting on ", " would truncate the value to `[1`.
            value, _ = json.JSONDecoder().raw_decode(fragment)
        except json.JSONDecodeError:
            return None
        return visualize(value, spec.kind)
    return None


def prepare_workspace(
    problem: Problem,
    language: str,
    *,
    stub: str,
    previous_attempt: str | None = None,
    root: Path | None = None,
) -> Workspace:
    base = Path(tempfile.mkdtemp(prefix=f"algorhythm-{problem.slug}-", dir=root))
    extension = LANGUAGES[language]

    statement_path = base / "statement.md"
    solution_path = base / f"solution.{extension}"
    results_path = base / "results.txt"
    review_path = base / "review.md"
    meta_path = base / "session.json"

    statement_path.write_text(_render_statement(problem))
    solution_path.write_text(previous_attempt if previous_attempt else stub)
    results_path.write_text("")
    review_path.write_text("")
    meta_path.write_text(
        json.dumps(
            {
                "slug": problem.slug,
                "language": language,
                "entry_point": problem.entry_point,
                "started_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            indent=2,
        )
    )

    return Workspace(
        dir=base,
        statement_path=statement_path,
        solution_path=solution_path,
        results_path=results_path,
        review_path=review_path,
        meta_path=meta_path,
        language=language,
        slug=problem.slug,
    )


def _lua_string(value: str) -> str:
    """Escape a value for embedding in a single-quoted Lua literal.

    A workspace path is derived from the problem slug and a temp directory,
    but the temp root is configurable and a home directory can legitimately
    contain an apostrophe (`/Users/O'Brien/...`), which would otherwise
    terminate the literal and produce a syntax error at startup.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def workspace_from_dir(workspace_dir: Path) -> Workspace:
    """Rebuild a Workspace from a directory `prepare_workspace` created.

    The editor invokes `algorhythm internal-test <dir>` with only a path, so
    something has to reconstitute the rest. Doing it here keeps the file
    layout described in exactly one place — hand-rebuilding it in the CLI
    means renaming a file in this module fails at runtime over there, with a
    FileNotFoundError rather than anything that points at the cause.
    """
    meta = json.loads((workspace_dir / "session.json").read_text())
    language = meta["language"]
    return Workspace(
        dir=workspace_dir,
        statement_path=workspace_dir / "statement.md",
        solution_path=workspace_dir / f"solution.{LANGUAGES[language]}",
        results_path=workspace_dir / "results.txt",
        review_path=workspace_dir / "review.md",
        meta_path=workspace_dir / "session.json",
        language=language,
        slug=meta["slug"],
    )


def nvim_command(workspace: Workspace) -> list[str]:
    return [
        "nvim",
        "-c",
        f"luafile {_LUA_MODULE}",
        "-c",
        f"lua require('algorhythm').setup('{_lua_string(str(workspace.dir))}')",
        str(workspace.solution_path),
    ]


def launch(workspace: Workspace, *, runner=subprocess.run) -> int:
    result = runner(nvim_command(workspace))
    return getattr(result, "returncode", 0)
```

- [ ] **Step 4: Implement `algorhythm/editor/lua/algorhythm.lua`**

```lua
-- Layout and hooks for one rep.
--
--   left  : statement, read-only
--   right : your solution
--   below : test results, then the review
--
-- :w      runs the tests
-- :Review asks the local model for a review
--
-- Both shell out to the algorhythm CLI, which owns all the real logic; this
-- file only moves text between buffers.

local M = {}

local function open_readonly_split(path, opts)
  vim.cmd(opts.command .. " " .. vim.fn.fnameescape(path))
  vim.bo.buftype = "nofile"
  vim.bo.swapfile = false
  vim.bo.modifiable = false
  vim.bo.filetype = opts.filetype or "markdown"
  if opts.height then vim.cmd("resize " .. opts.height) end
  if opts.width then vim.cmd("vertical resize " .. opts.width) end
  return vim.api.nvim_get_current_win()
end

local function replace_buffer(win, path)
  if not win or not vim.api.nvim_win_is_valid(win) then return end
  local buf = vim.api.nvim_win_get_buf(win)
  local lines = {}
  for line in io.lines(path) do table.insert(lines, line) end
  vim.bo[buf].modifiable = true
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = false
end

local function run(cmd, output_path, win, label)
  vim.notify(label .. "...", vim.log.levels.INFO)
  vim.fn.jobstart(cmd, {
    on_exit = function()
      vim.schedule(function()
        replace_buffer(win, output_path)
        vim.notify(label .. " done", vim.log.levels.INFO)
      end)
    end,
  })
end

function M.setup(dir)
  M.dir = dir
  local solution_win = vim.api.nvim_get_current_win()

  -- Statement on the left, roughly a third of the width.
  vim.cmd("topleft vsplit " .. vim.fn.fnameescape(dir .. "/statement.md"))
  vim.bo.buftype = "nofile"
  vim.bo.modifiable = false
  vim.bo.filetype = "markdown"
  vim.cmd("vertical resize " .. math.floor(vim.o.columns / 3))
  vim.wo.wrap = true

  vim.api.nvim_set_current_win(solution_win)

  -- Results along the bottom.
  M.results_win = open_readonly_split(dir .. "/results.txt", {
    command = "botright split",
    filetype = "text",
    height = 12,
  })
  vim.api.nvim_set_current_win(solution_win)

  vim.api.nvim_create_autocmd("BufWritePost", {
    pattern = dir .. "/solution.*",
    callback = function()
      run(
        { "algorhythm", "internal-test", dir },
        dir .. "/results.txt",
        M.results_win,
        "Running tests"
      )
    end,
  })

  vim.api.nvim_create_user_command("Review", function()
    if not (M.review_win and vim.api.nvim_win_is_valid(M.review_win)) then
      local current = vim.api.nvim_get_current_win()
      M.review_win = open_readonly_split(dir .. "/review.md", {
        command = "botright vsplit",
        filetype = "markdown",
        width = math.floor(vim.o.columns / 3),
      })
      vim.wo.wrap = true
      vim.api.nvim_set_current_win(current)
    end
    run(
      { "algorhythm", "internal-review", dir },
      dir .. "/review.md",
      M.review_win,
      "Reviewing"
    )
  end, {})

  vim.notify("algorhythm: :w runs tests, :Review grades", vim.log.levels.INFO)
end

package.loaded["algorhythm"] = M
return M
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
mkdir -p tests/editor && touch algorhythm/editor/__init__.py tests/editor/__init__.py
python -m pytest tests/editor -v
```

Expected: PASS — 14 passed

- [ ] **Step 6: Commit**

```bash
git add algorhythm/editor/ tests/editor/
git commit -m "feat(editor): nvim workspace with statement, results, and review splits

Each rep gets an isolated scratch directory, so an abandoned rep leaves no
trace. The Lua module only shuttles text between buffers — :w and :Review
shell out to the CLI, which owns all the logic."
```

---

## Task 13: Rep orchestration and CLI

The whole loop, as a testable module with its dependencies injected, plus the CLI that drives it. After this task the tool works end to end with plain terminal prompts; Task 14 replaces those with the TUI.

**Files:**
- Create: `algorhythm/session.py`
- Create: `algorhythm/cli.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: everything from Tasks 1-12.
- Produces:
  - `RepDeps(load_problem, load_tests, reference_source, stub_source, prepare, launch, run_tests, reviewer, now, ask_grade, record_attempt)`
  - `RepOutcome(slug, language, run_result, review, grade, proposed_grade, elapsed_ms, abandoned)`
  - `run_rep(item, deps) -> RepOutcome`
  - `persist(outcome, repo, deps.now) -> None`
  - CLI commands: `review`, `add`, `list`, `stats`, `internal-test`, `internal-review`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session.py`:

```python
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem
from algorhythm.reviewer.protocol import Review, ReviewerUnavailable
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import NEW, Grade, SchedulingState
from algorhythm.session import RepDeps, persist, run_rep
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)

PASSING = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.PASS)])


def problem() -> Problem:
    return Problem(
        slug="two-sum",
        number=1,
        title="Two Sum",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=[ParamSpec("nums")],
        return_kind="raw",
        entry_point="twoSum",
        fetched_at=NOW,
    )


class FakeWorkspace:
    def __init__(self, source="class Solution: pass"):
        self.language = "python"
        self.slug = "two-sum"
        self._source = source

    @property
    def solution_path(self):
        class P:
            def __init__(self, text):
                self._text = text

            def read_text(self_inner):
                return self._source

        return P(self._source)


def deps(**overrides) -> RepDeps:
    base = dict(
        load_problem=lambda slug: problem(),
        load_tests=lambda slug: [],
        reference_source=lambda slug, lang: "# reference",
        stub_source=lambda slug, lang: "class Solution: pass",
        prepare=lambda p, lang, stub, previous: FakeWorkspace(),
        launch=lambda ws: 0,
        run_tests=lambda p, ws, cases: PASSING,
        reviewer=FakeReviewer(),
        now=lambda: NOW,
        ask_grade=lambda review, run: Grade.GOOD,
        record_attempt=lambda slug, source, lang: None,
    )
    base.update(overrides)
    return RepDeps(**base)


class FakeReviewer:
    def __init__(self, review=None, raises=None):
        self._review = review or Review(
            text="Hash map is right.", proposed_grade=Grade.GOOD, model="fake"
        )
        self._raises = raises

    def review(self, request):
        if self._raises:
            raise self._raises
        return self._review


def item(slug="two-sum", is_new=True) -> QueueItem:
    return QueueItem(slug=slug, is_new=is_new, due_at=None, state=NEW)


# -- the happy path -------------------------------------------------------

def test_rep_returns_the_confirmed_grade():
    outcome = run_rep(item(), deps())
    assert outcome.grade is Grade.GOOD
    assert outcome.abandoned is False


def test_rep_carries_the_run_result_and_review():
    outcome = run_rep(item(), deps())
    assert outcome.run_result is PASSING
    assert "Hash map" in outcome.review.text


def test_rep_records_what_the_model_proposed_separately_from_the_grade():
    """The distinction matters for judging the model's calibration later."""
    reviewer = FakeReviewer(
        Review(text="x", proposed_grade=Grade.EASY, model="fake")
    )
    outcome = run_rep(item(), deps(reviewer=reviewer, ask_grade=lambda r, s: Grade.HARD))
    assert outcome.proposed_grade is Grade.EASY
    assert outcome.grade is Grade.HARD


def test_rep_measures_elapsed_time():
    clock = iter([NOW, NOW.replace(minute=25)])
    outcome = run_rep(item(), deps(now=lambda: next(clock)))
    assert outcome.elapsed_ms == 25 * 60 * 1000


def test_previous_attempt_is_offered_on_a_repeat_rep():
    seen = {}

    def prepare(p, lang, stub, previous):
        seen["previous"] = previous
        return FakeWorkspace()

    run_rep(
        item(is_new=False),
        deps(prepare=prepare, load_previous_attempt=lambda slug, lang: "old code"),
    )
    assert seen["previous"] == "old code"


# -- degradation ----------------------------------------------------------

def test_unavailable_reviewer_does_not_block_the_rep():
    """The governing rule: nothing blocks the SRS loop."""
    reviewer = FakeReviewer(raises=ReviewerUnavailable("ollama down"))
    outcome = run_rep(item(), deps(reviewer=reviewer))
    assert outcome.grade is Grade.GOOD
    assert outcome.review is None


def test_unavailable_reviewer_still_asks_for_a_grade():
    asked = []
    reviewer = FakeReviewer(raises=ReviewerUnavailable("down"))

    def ask(review, run):
        asked.append(review)
        return Grade.HARD

    run_rep(item(), deps(reviewer=reviewer, ask_grade=ask))
    assert asked == [None]


def test_missing_reference_still_produces_a_review():
    outcome = run_rep(item(), deps(reference_source=lambda slug, lang: None))
    assert outcome.review is not None


def test_declining_to_grade_marks_the_rep_abandoned():
    outcome = run_rep(item(), deps(ask_grade=lambda review, run: None))
    assert outcome.abandoned is True
    assert outcome.grade is None


def test_compile_error_still_reaches_the_grading_step():
    broken = RunResult(compile_error="SyntaxError")
    outcome = run_rep(item(), deps(run_tests=lambda p, ws, c: broken))
    assert outcome.run_result.compile_error == "SyntaxError"
    assert outcome.grade is Grade.GOOD


# -- persistence ----------------------------------------------------------

def test_persist_writes_a_review_row_and_schedules_the_next_rep():
    repo = Repository(connect(":memory:"))
    outcome = run_rep(item(), deps())
    persist(outcome, repo, NOW)

    assert repo.counts()["reviews"] == 1
    row = repo.get_schedule("two-sum")
    assert row is not None
    assert row.state.reps == 1
    assert row.due_at > NOW


def test_persist_applies_sm2_from_the_existing_state():
    repo = Repository(connect(":memory:"))
    from algorhythm.store.repository import ScheduleRow

    repo.upsert_schedule(
        ScheduleRow(
            slug="two-sum",
            due_at=NOW,
            state=SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0),
            last_grade=Grade.GOOD,
            last_reviewed_at=NOW,
        )
    )
    persist(run_rep(item(is_new=False), deps()), repo, NOW)
    assert repo.get_schedule("two-sum").state.interval_days == 25.0


def test_persist_ignores_an_abandoned_rep():
    repo = Repository(connect(":memory:"))
    outcome = run_rep(item(), deps(ask_grade=lambda r, s: None))
    persist(outcome, repo, NOW)
    assert repo.counts()["reviews"] == 0
    assert repo.get_schedule("two-sum") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.session'`

- [ ] **Step 3: Implement `algorhythm/session.py`**

```python
"""One rep, start to finish.

Dependencies are injected rather than imported so the whole loop is
testable without nvim, Ollama, or a filesystem.

The governing rule from the spec is enforced here: nothing blocks the SRS
loop. A dead reviewer, a missing reference, and a compile error all still
reach the grading step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from algorhythm.reviewer.protocol import (
    Review,
    ReviewerUnavailable,
    ReviewRequest,
)
from algorhythm.runner.harness import RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import Grade, due_at, review as apply_grade
from algorhythm.store.repository import Repository, ReviewRecord, ScheduleRow


@dataclass
class RepDeps:
    load_problem: Callable[[str], Any]
    load_tests: Callable[[str], list]
    reference_source: Callable[[str, str], str | None]
    stub_source: Callable[[str, str], str]
    prepare: Callable[..., Any]
    launch: Callable[[Any], int]
    run_tests: Callable[..., RunResult]
    reviewer: Any
    now: Callable[[], datetime]
    ask_grade: Callable[[Review | None, RunResult], Grade | None]
    record_attempt: Callable[[str, str, str], None]
    load_previous_attempt: Callable[[str, str], str | None] = lambda slug, lang: None
    language: str = "python"


@dataclass(frozen=True)
class RepOutcome:
    slug: str
    language: str
    run_result: RunResult
    review: Review | None
    grade: Grade | None
    proposed_grade: Grade | None
    elapsed_ms: int
    state_before: Any
    abandoned: bool = False


def run_rep(item: QueueItem, deps: RepDeps) -> RepOutcome:
    started = deps.now()
    problem = deps.load_problem(item.slug)
    language = deps.language

    workspace = deps.prepare(
        problem,
        language,
        deps.stub_source(item.slug, language),
        deps.load_previous_attempt(item.slug, language),
    )
    deps.launch(workspace)

    source = workspace.solution_path.read_text()
    deps.record_attempt(item.slug, source, language)

    run_result = deps.run_tests(problem, workspace, deps.load_tests(item.slug))

    try:
        review = deps.reviewer.review(
            ReviewRequest(
                problem=problem,
                language=language,
                solution_source=source,
                reference_source=deps.reference_source(item.slug, language),
                run_result=run_result,
            )
        )
    except ReviewerUnavailable:
        review = None  # the loop continues; the user grades unaided

    grade = deps.ask_grade(review, run_result)
    finished = deps.now()

    return RepOutcome(
        slug=item.slug,
        language=language,
        run_result=run_result,
        review=review,
        grade=grade,
        proposed_grade=review.proposed_grade if review else None,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        state_before=item.state,
        abandoned=grade is None,
    )


def persist(outcome: RepOutcome, repo: Repository, now: datetime) -> None:
    """Write the review row and reschedule. A no-op for an abandoned rep."""
    if outcome.abandoned or outcome.grade is None:
        return

    existing = repo.get_schedule(outcome.slug)
    before = existing.state if existing else outcome.state_before
    after = apply_grade(before, outcome.grade)

    repo.record_review(
        ReviewRecord(
            slug=outcome.slug,
            reviewed_at=now,
            grade=outcome.grade,
            proposed_grade=outcome.proposed_grade,
            interval_before=before.interval_days,
            interval_after=after.interval_days,
            ease_before=before.ease,
            ease_after=after.ease,
            elapsed_ms=outcome.elapsed_ms,
            tests_passed=outcome.run_result.passed,
            tests_total=outcome.run_result.total,
            language=outcome.language,
            model=outcome.review.model if outcome.review else None,
            review_text=outcome.review.text if outcome.review else None,
        )
    )

    repo.upsert_schedule(
        ScheduleRow(
            slug=outcome.slug,
            due_at=due_at(after, now),
            state=after,
            last_grade=outcome.grade,
            last_reviewed_at=now,
        )
    )
```

- [ ] **Step 4: Implement `algorhythm/cli.py`**

```python
"""Typer entry point.

`internal-test` and `internal-review` are called by the nvim Lua module,
not by humans; they read a workspace directory and write their output to a
file the editor then reloads.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import typer

from algorhythm import config
from algorhythm.catalog import store as catalog
from algorhythm.catalog.models import LANGUAGES
from algorhythm.runner.cpp_runner import run_cpp
from algorhythm.runner.python_runner import run_python
from algorhythm.scheduler.queue import QueueConfig, build_queue
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository

app = typer.Typer(add_completion=False, help="Spaced repetition for DSA interviews.")


def _repo() -> Repository:
    return Repository(connect(config.db_path()))


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _read(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def _execute(problem, workspace, cases):
    runner = run_python if workspace.language == "python" else run_cpp
    return runner(problem, workspace.solution_path, cases)


@app.command("list")
def list_problems() -> None:
    """Show the library and each problem's next due date."""
    repo = _repo()
    for slug in catalog.list_slugs():
        row = repo.get_schedule(slug)
        when = row.due_at.date().isoformat() if row else "unseen"
        reps = row.state.reps if row else 0
        typer.echo(f"{when:>10}  reps={reps:<3} {slug}")


@app.command()
def stats() -> None:
    """Counts of scheduled problems, reviews, and attempts."""
    for key, value in _repo().counts().items():
        typer.echo(f"{key:>10}: {value}")


@app.command()
def add(slug: str) -> None:
    """Fetch a problem from LeetCode and add it to the library."""
    from algorhythm.catalog.fetch import FetchError, extract_stubs, fetch_question

    try:
        problem = fetch_question(slug)
    except FetchError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    directory = catalog.save_problem(problem)
    typer.echo(f"added {problem.number}. {problem.title} -> {directory}")


@app.command("internal-test", hidden=True)
def internal_test(workspace_dir: Path) -> None:
    """Run the tests for a workspace and write results.txt. Called by nvim."""
    from algorhythm.editor.session import workspace_from_dir

    workspace = workspace_from_dir(workspace_dir)
    problem = catalog.load_problem(workspace.slug)
    cases = catalog.load_tests(workspace.slug)

    result = _execute(problem, workspace, cases)

    lines = [result.summary, ""]
    if result.compile_error:
        lines.append(result.compile_error)
    for case in result.cases:
        marker = "ok  " if case.status.value == "pass" else "FAIL"
        lines.append(f"{marker} {case.id}  {case.status.value}")
        if case.status.value != "pass":
            lines.append(f"       expected: {case.expected!r}")
            lines.append(f"       actual:   {case.actual!r}")
            if case.error:
                lines.append(f"       error:    {case.error.strip()}")
    workspace.results_path.write_text("\n".join(lines) + "\n")


@app.command("internal-review", hidden=True)
def internal_review(workspace_dir: Path) -> None:
    """Review the workspace solution and write review.md. Called by nvim."""
    from algorhythm.reviewer.ollama import OllamaReviewer
    from algorhythm.reviewer.protocol import ReviewerUnavailable, ReviewRequest

    from algorhythm.editor.session import workspace_from_dir

    workspace = workspace_from_dir(workspace_dir)
    problem = catalog.load_problem(workspace.slug)
    language = workspace.language

    solution = workspace.solution_path.read_text()
    cases = catalog.load_tests(workspace.slug)

    run_result = _execute(problem, workspace, cases)

    request = ReviewRequest(
        problem=problem,
        language=language,
        solution_source=solution,
        reference_source=_read(catalog.reference_path(workspace.slug, language)),
        run_result=run_result,
    )

    try:
        review = OllamaReviewer().review(request)
        body = review.text
        if review.proposed_grade:
            body += f"\n\n---\nProposed grade: **{review.proposed_grade.value}**"
            if review.grade_reason:
                body += f"\n{review.grade_reason}"
    except ReviewerUnavailable as exc:
        body = f"Review unavailable.\n\n{exc}"

    (workspace_dir / "review.md").write_text(body + "\n")


@app.command()
def review(
    limit: int = typer.Option(5, help="Maximum problems in today's queue."),
    new: int = typer.Option(2, help="Maximum unseen problems to introduce."),
) -> None:
    """Work through today's queue."""
    from algorhythm.tui.app import run_queue

    repo = _repo()
    queue = build_queue(
        repo,
        catalog.list_slugs(),
        _now(),
        QueueConfig(daily_cap=limit, new_per_day=new),
    )
    if not queue:
        typer.echo("Nothing due. Enjoy the day off.")
        raise typer.Exit()

    run_queue(queue, repo)


if __name__ == "__main__":
    app()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_session.py -v`
Expected: PASS — 13 passed

- [ ] **Step 6: Commit**

```bash
git add algorhythm/session.py algorhythm/cli.py tests/test_session.py
git commit -m "feat(session): rep orchestration with injected dependencies

The whole loop is testable without nvim, Ollama, or a filesystem. Enforces
the spec's governing rule with tests: a dead reviewer, a missing reference,
and a compile error all still reach the grading step."
```

---

## Task 14: Textual TUI

Replaces the plain prompts with the queue view and grade confirmation. Presentation only — all logic lives in `session.py`, so the testable surface here is the pure formatting and choice-ordering helpers plus one end-to-end pilot test.

**Files:**
- Create: `algorhythm/tui/__init__.py`
- Create: `algorhythm/tui/format.py`
- Create: `algorhythm/tui/app.py`
- Test: `tests/tui/test_format.py`
- Test: `tests/tui/test_app.py`

**Interfaces:**
- Consumes: `QueueItem` from Task 3; `Review`, `RunResult` from Tasks 8 and 11; `RepDeps`, `run_rep`, `persist` from Task 13.
- Produces:
  - `format_queue_row(item, title, difficulty) -> str`
  - `format_results(run_result) -> str`
  - `grade_choices(proposed: Grade | None) -> list[tuple[Grade, bool]]`
  - `GradeScreen(review, run_result)` — a Textual screen returning `Grade | None`
  - `run_queue(queue, repo) -> None`

- [ ] **Step 1: Write the failing formatting tests**

Create `tests/tui/test_format.py`:

```python
from datetime import datetime, timedelta, timezone

from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import NEW, Grade, SchedulingState
from algorhythm.tui.format import format_queue_row, format_results, grade_choices

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def test_new_items_are_marked_as_new():
    item = QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)
    assert "new" in format_queue_row(item, "Two Sum", "Easy").lower()


def test_review_items_show_how_overdue_they_are():
    item = QueueItem(
        slug="two-sum",
        is_new=False,
        due_at=NOW - timedelta(days=3),
        state=SchedulingState(interval_days=5.0, ease=2.5, reps=2, lapses=0),
        )
    row = format_queue_row(item, "Two Sum", "Easy", now=NOW)
    assert "3d" in row


def test_queue_row_includes_the_title_and_difficulty():
    item = QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)
    row = format_queue_row(item, "Two Sum", "Easy")
    assert "Two Sum" in row and "Easy" in row


def test_results_summary_leads_the_output():
    run = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.PASS)])
    assert format_results(run).splitlines()[0] == "1/1 passed"


def test_results_list_only_the_failures():
    run = RunResult(
        cases=[
            CaseResult(id="c1", status=CaseStatus.PASS),
            CaseResult(id="c2", status=CaseStatus.FAIL, expected=1, actual=2),
        ]
    )
    text = format_results(run)
    assert "c2" in text
    assert "c1" not in text


def test_results_show_the_compile_error_when_there_is_one():
    assert "SyntaxError" in format_results(RunResult(compile_error="SyntaxError: x"))


def test_grade_choices_are_in_anki_order():
    assert [g for g, _ in grade_choices(None)] == [
        Grade.AGAIN,
        Grade.HARD,
        Grade.GOOD,
        Grade.EASY,
    ]


def test_the_proposed_grade_is_preselected():
    assert dict(grade_choices(Grade.HARD))[Grade.HARD] is True


def test_only_one_grade_is_preselected():
    assert sum(1 for _, selected in grade_choices(Grade.HARD) if selected) == 1


def test_good_is_the_default_when_nothing_was_proposed():
    """A dead reviewer must still leave a sensible default under the cursor."""
    assert dict(grade_choices(None))[Grade.GOOD] is True
```

- [ ] **Step 2: Write the failing app test**

Create `tests/tui/test_app.py`:

```python
import pytest

from algorhythm.reviewer.protocol import Review
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.sm2 import Grade
from algorhythm.tui.app import GradeScreen

PASSING = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.PASS)])


@pytest.mark.asyncio
async def test_enter_accepts_the_proposed_grade():
    review = Review(text="Looks right.", proposed_grade=Grade.HARD, model="fake")
    app = GradeScreen.host(review, PASSING)
    async with app.run_test() as pilot:
        await pilot.press("enter")
    assert app.result is Grade.HARD


@pytest.mark.asyncio
async def test_arrow_keys_override_the_proposal():
    review = Review(text="x", proposed_grade=Grade.HARD, model="fake")
    app = GradeScreen.host(review, PASSING)
    async with app.run_test() as pilot:
        await pilot.press("right", "enter")
    assert app.result is Grade.GOOD


@pytest.mark.asyncio
async def test_escape_abandons_the_rep():
    app = GradeScreen.host(None, PASSING)
    async with app.run_test() as pilot:
        await pilot.press("escape")
    assert app.result is None


@pytest.mark.asyncio
async def test_review_text_is_displayed():
    review = Review(text="Use a hash map.", proposed_grade=Grade.GOOD, model="fake")
    app = GradeScreen.host(review, PASSING)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "hash map" in app.screen_text().lower()


@pytest.mark.asyncio
async def test_missing_review_shows_an_explanation_not_a_blank_pane():
    app = GradeScreen.host(None, PASSING)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "unavailable" in app.screen_text().lower()
```

Add `pytest-asyncio` to the dev extras in `pyproject.toml`:

```toml
dev = ["pytest>=8.0", "pytest-cov>=5.0", "pytest-asyncio>=0.24"]
```

and configure it:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
asyncio_mode = "auto"
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `python -m pytest tests/tui -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.tui'`

- [ ] **Step 4: Implement `algorhythm/tui/format.py`**

```python
"""Pure formatting helpers. No Textual imports, so these stay trivially
testable."""

from __future__ import annotations

from datetime import datetime, timezone

from algorhythm.runner.harness import CaseStatus, RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import Grade

GRADE_ORDER = (Grade.AGAIN, Grade.HARD, Grade.GOOD, Grade.EASY)
DEFAULT_GRADE = Grade.GOOD


def format_queue_row(
    item: QueueItem,
    title: str,
    difficulty: str,
    *,
    now: datetime | None = None,
) -> str:
    if item.is_new:
        marker = "new"
    else:
        moment = now or datetime.now(tz=timezone.utc)
        overdue_days = max(0, (moment - item.due_at).days)
        marker = f"{overdue_days}d late" if overdue_days else "due"
    return f"{marker:>9}  {difficulty:<6}  {title}"


def format_results(result: RunResult) -> str:
    if result.compile_error:
        return f"compile error\n\n{result.compile_error}"

    lines = [result.summary]
    for case in result.cases:
        if case.status is CaseStatus.PASS:
            continue
        lines.append(f"\n{case.id}: {case.status.value}")
        if case.status is CaseStatus.FAIL:
            lines.append(f"  expected {case.expected!r}")
            lines.append(f"  actual   {case.actual!r}")
        elif case.error:
            lines.append(f"  {case.error.strip().splitlines()[-1]}")
    return "\n".join(lines)


def grade_choices(proposed: Grade | None) -> list[tuple[Grade, bool]]:
    """Anki's four buttons, with exactly one preselected."""
    selected = proposed or DEFAULT_GRADE
    return [(grade, grade is selected) for grade in GRADE_ORDER]
```

- [ ] **Step 5: Implement `algorhythm/tui/app.py`**

```python
"""Textual presentation. All logic lives in session.py."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from algorhythm.catalog import store as catalog
from algorhythm.reviewer.protocol import Review
from algorhythm.runner.harness import RunResult
from algorhythm.scheduler.sm2 import Grade
from algorhythm.tui.format import format_queue_row, format_results, grade_choices


class GradeScreen(App):
    """Shows the review and collects a grade. Enter accepts the highlighted
    option, arrows move, escape abandons the rep."""

    CSS = """
    #review { height: 1fr; border: round $accent; padding: 1 2; }
    #results { height: auto; max-height: 12; border: round $secondary; padding: 0 2; }
    #grades { height: auto; align: center middle; padding: 1; }
    .grade { padding: 0 3; }
    .selected { background: $accent; color: $text; text-style: bold; }
    """

    BINDINGS = [
        Binding("left", "move(-1)", "Previous"),
        Binding("right", "move(1)", "Next"),
        Binding("enter", "accept", "Accept"),
        Binding("escape", "abandon", "Skip"),
    ]

    def __init__(self, review: Review | None, run_result: RunResult) -> None:
        super().__init__()
        self._review = review
        self._run_result = run_result
        self._choices = grade_choices(review.proposed_grade if review else None)
        self._index = next(i for i, (_, sel) in enumerate(self._choices) if sel)
        self.result: Grade | None = None

    # -- test helpers -----------------------------------------------------

    @classmethod
    def host(cls, review: Review | None, run_result: RunResult) -> "GradeScreen":
        return cls(review, run_result)

    def screen_text(self) -> str:
        return " ".join(
            str(widget.renderable)
            for widget in self.query(Static)
            if hasattr(widget, "renderable")
        )

    # -- composition ------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        body = (
            self._review.text
            if self._review
            else "Review unavailable — Ollama could not be reached. Grade from "
            "your own sense of how the rep went."
        )
        with Vertical():
            yield Static(body, id="review")
            yield Static(format_results(self._run_result), id="results")
            with Horizontal(id="grades"):
                for index, (grade, _) in enumerate(self._choices):
                    classes = "grade selected" if index == self._index else "grade"
                    yield Label(grade.value, classes=classes, id=f"grade-{index}")
        yield Footer()

    # -- actions ----------------------------------------------------------

    def action_move(self, delta: int) -> None:
        self._index = (self._index + delta) % len(self._choices)
        for index in range(len(self._choices)):
            label = self.query_one(f"#grade-{index}", Label)
            label.set_classes("grade selected" if index == self._index else "grade")

    def action_accept(self) -> None:
        self.result = self._choices[self._index][0]
        self.exit()

    def action_abandon(self) -> None:
        self.result = None
        self.exit()


class QueueScreen(App):
    """Shows today's queue and returns the chosen index."""

    BINDINGS = [Binding("escape", "quit_queue", "Quit")]

    def __init__(self, rows: list[str]) -> None:
        super().__init__()
        self._rows = rows
        self.chosen: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield ListView(*(ListItem(Label(row)) for row in self._rows))
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.chosen = event.list_view.index
        self.exit()

    def action_quit_queue(self) -> None:
        self.chosen = None
        self.exit()


def run_queue(queue, repo) -> None:
    """Drive the queue to completion. Imported lazily by the CLI so a plain
    `algorhythm list` never pays Textual's import cost."""
    from algorhythm.editor.session import launch, prepare_workspace
    from algorhythm.reviewer.ollama import OllamaReviewer
    from algorhythm.runner.cpp_runner import run_cpp
    from algorhythm.runner.python_runner import run_python
    from algorhythm.session import RepDeps, persist, run_rep

    remaining = list(queue)
    while remaining:
        rows = []
        for entry in remaining:
            problem = catalog.load_problem(entry.slug)
            rows.append(format_queue_row(entry, problem.title, problem.difficulty))

        picker = QueueScreen(rows)
        picker.run()
        if picker.chosen is None:
            return

        item = remaining.pop(picker.chosen)
        language = repo.last_language(item.slug) or "python"

        def ask_grade(review, run_result):
            screen = GradeScreen(review, run_result)
            screen.run()
            return screen.result

        deps = RepDeps(
            load_problem=catalog.load_problem,
            load_tests=catalog.load_tests,
            reference_source=lambda slug, lang: _read_optional(
                catalog.reference_path(slug, lang)
            ),
            stub_source=lambda slug, lang: _read_optional(
                catalog.stub_path(slug, lang)
            )
            or "",
            prepare=lambda problem, lang, stub, previous: prepare_workspace(
                problem, lang, stub=stub, previous_attempt=previous
            ),
            launch=launch,
            run_tests=lambda problem, workspace, cases: (
                run_python if workspace.language == "python" else run_cpp
            )(problem, workspace.solution_path, cases),
            reviewer=OllamaReviewer(),
            now=lambda: datetime.now(tz=timezone.utc),
            ask_grade=ask_grade,
            record_attempt=lambda slug, source, lang: repo.record_attempt(
                slug, datetime.now(tz=timezone.utc), lang, source
            ),
            language=language,
        )

        outcome = run_rep(item, deps)
        persist(outcome, repo, datetime.now(tz=timezone.utc))


def _read_optional(path) -> str | None:
    return path.read_text() if path.exists() else None
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
mkdir -p tests/tui && touch algorhythm/tui/__init__.py tests/tui/__init__.py
python -m pip install -e ".[dev]"
python -m pytest tests/tui -v
```

Expected: PASS — 15 passed

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS — all tests from Tasks 1-14

- [ ] **Step 8: Commit**

```bash
git add algorhythm/tui/ tests/tui/ pyproject.toml
git commit -m "feat(tui): queue view and grade confirmation

Anki's four buttons with the model's proposal preselected; enter accepts,
arrows override, escape abandons. Formatting helpers are pure and imported
without Textual, so most of the surface is testable without a pilot."
```

---

## Task 15: Seeding the library

Bulk-fetches the curated list, imports reference solutions from `neetcode-gh/leetcode`, and generates oracle test cases. Reports exactly which problems ended up without a reference, since those need a hand-written one before their reviews are worth anything.

**Files:**
- Create: `algorhythm/seed.py`
- Create: `seeds/neetcode150.txt`
- Modify: `algorhythm/cli.py` — add the `seed` command
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `fetch_question`, `extract_stubs` from Task 5; `save_problem`, `save_tests` from Task 4; `generate_oracle_cases` from Task 10.
- Produces:
  - `read_slug_list(path) -> list[str]`
  - `neetcode_reference_urls(number, slug) -> dict[str, list[str]]`
  - `SeedReport(added, skipped, missing_reference, failed)`
  - `seed_problems(slugs, *, fetch, fetch_reference, root=None) -> SeedReport`

- [ ] **Step 1: Create `seeds/neetcode150.txt`**

⚠️ **This file ships with a verified starter subset, not all 150.** Fabricating 150 slugs from memory would produce fetch failures that look like bugs. Populate the rest from neetcode.io's published list before the first full seed run — the format is one slug per line, `#` for comments.

```
# NeetCode 150 — one LeetCode slug per line.
# Starter subset; extend from https://neetcode.io/practice
# Arrays & Hashing
contains-duplicate
valid-anagram
two-sum
group-anagrams
top-k-frequent-elements
product-of-array-except-self
longest-consecutive-sequence
# Two Pointers
valid-palindrome
two-sum-ii-input-array-is-sorted
3sum
container-with-most-water
# Sliding Window
best-time-to-buy-and-sell-stock
longest-substring-without-repeating-characters
longest-repeating-character-replacement
# Stack
valid-parentheses
# Binary Search
binary-search
search-a-2d-matrix
koko-eating-bananas
# Linked List
reverse-linked-list
merge-two-sorted-lists
linked-list-cycle
# Trees
invert-binary-tree
maximum-depth-of-binary-tree
same-tree
binary-tree-level-order-traversal
validate-binary-search-tree
# Graphs
number-of-islands
clone-graph
course-schedule
# Dynamic Programming
climbing-stairs
house-robber
longest-palindromic-substring
coin-change
word-break
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_seed.py`:

```python
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem
from algorhythm.catalog.store import list_slugs, load_problem
from algorhythm.seed import (
    neetcode_reference_urls,
    read_slug_list,
    seed_problems,
)

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def problem(slug="two-sum", number=1) -> Problem:
    return Problem(
        slug=slug,
        number=number,
        title=slug.replace("-", " ").title(),
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="statement",
        constraints=[],
        examples=[],
        params=[ParamSpec("nums")],
        return_kind="raw",
        entry_point="solve",
        fetched_at=NOW,
    )


def fake_fetch(slug):
    if slug == "explodes":
        raise RuntimeError("404 from LeetCode")
    return problem(slug, number=abs(hash(slug)) % 900 + 1)


def fake_reference(number, slug, language):
    if slug == "no-reference":
        return None
    return f"# {language} reference for {slug}"


# -- slug list ------------------------------------------------------------

def test_reads_one_slug_per_line(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("two-sum\nvalid-anagram\n")
    assert read_slug_list(path) == ["two-sum", "valid-anagram"]


def test_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# heading\n\ntwo-sum\n   \n# another\nvalid-anagram\n")
    assert read_slug_list(path) == ["two-sum", "valid-anagram"]


def test_strips_surrounding_whitespace(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("  two-sum  \n")
    assert read_slug_list(path) == ["two-sum"]


# -- reference URLs -------------------------------------------------------

def test_reference_urls_cover_both_languages():
    urls = neetcode_reference_urls(102, "binary-tree-level-order-traversal")
    assert set(urls) == {"python", "cpp"}


def test_reference_urls_use_the_zero_padded_number():
    urls = neetcode_reference_urls(1, "two-sum")
    assert any("0001-two-sum" in url for url in urls["python"])


def test_reference_urls_offer_more_than_one_candidate_layout():
    """The upstream repo has reorganised before; try several paths and let
    the caller report which problems came up empty."""
    assert len(neetcode_reference_urls(1, "two-sum")["python"]) > 1


# -- seeding --------------------------------------------------------------

def test_seeds_each_slug(tmp_path):
    report = seed_problems(
        ["two-sum", "valid-anagram"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert report.added == ["two-sum", "valid-anagram"]
    assert sorted(list_slugs(root=tmp_path)) == ["two-sum", "valid-anagram"]


def test_writes_reference_solutions_for_both_languages(tmp_path):
    seed_problems(
        ["two-sum"], fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path
    )
    directory = next(tmp_path.iterdir())
    assert (directory / "reference.py").exists()
    assert (directory / "reference.cpp").exists()


def test_reports_problems_that_got_no_reference(tmp_path):
    report = seed_problems(
        ["no-reference"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert report.missing_reference == ["no-reference"]


def test_a_problem_without_a_reference_is_still_added(tmp_path):
    """Losing the reference costs you comparison, not the problem itself."""
    report = seed_problems(
        ["no-reference"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert "no-reference" in report.added


def test_a_fetch_failure_is_recorded_and_does_not_stop_the_run(tmp_path):
    report = seed_problems(
        ["two-sum", "explodes", "valid-anagram"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert [slug for slug, _ in report.failed] == ["explodes"]
    assert report.added == ["two-sum", "valid-anagram"]


def test_already_present_problems_are_skipped(tmp_path):
    kwargs = dict(fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path)
    seed_problems(["two-sum"], **kwargs)
    report = seed_problems(["two-sum"], **kwargs)
    assert report.skipped == ["two-sum"]
    assert report.added == []


def test_statement_survives_the_roundtrip(tmp_path):
    seed_problems(
        ["two-sum"], fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path
    )
    assert load_problem("two-sum", root=tmp_path).statement_md == "statement"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'algorhythm.seed'`

- [ ] **Step 4: Implement `algorhythm/seed.py`**

```python
"""Bulk library seeding.

Fetches each problem, imports a reference solution from neetcode-gh, and
generates oracle test cases. Nothing here aborts the whole run: a problem
that fails to fetch, or that has no available reference, is recorded and
the run continues. The report is the deliverable — it tells you exactly
which problems need hand-written references before their reviews mean
anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from algorhythm.catalog import store as catalog
from algorhythm.catalog.models import LANGUAGES, Problem
from algorhythm.oracle import generate_oracle_cases

RAW_BASE = "https://raw.githubusercontent.com/neetcode-gh/leetcode/main"

_LANGUAGE_DIRS = {"python": ("python", "py"), "cpp": ("cpp", "cpp")}


def read_slug_list(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    return [
        stripped
        for line in lines
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def neetcode_reference_urls(number: int, slug: str) -> dict[str, list[str]]:
    """Candidate raw URLs per language.

    The upstream repository has reorganised its layout before, so each
    language gets several candidates tried in order rather than one guess.
    """
    padded = f"{number:04d}"
    out: dict[str, list[str]] = {}
    for language, (directory, extension) in _LANGUAGE_DIRS.items():
        out[language] = [
            f"{RAW_BASE}/{directory}/{padded}-{slug}.{extension}",
            f"{RAW_BASE}/{directory}/{slug}.{extension}",
            f"{RAW_BASE}/{directory}/{padded}-{slug.replace('-', '_')}.{extension}",
        ]
    return out


@dataclass
class SeedReport:
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    missing_reference: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"added:   {len(self.added)}",
            f"skipped: {len(self.skipped)} (already present)",
            f"failed:  {len(self.failed)}",
        ]
        if self.missing_reference:
            lines.append("")
            lines.append(
                "No reference solution found — reviews for these will run "
                "without a comparison until you write one:"
            )
            lines += [f"  - {slug}" for slug in self.missing_reference]
        if self.failed:
            lines.append("")
            lines.append("Failed to fetch:")
            lines += [f"  - {slug}: {error}" for slug, error in self.failed]
        return "\n".join(lines)


def fetch_reference_from_github(
    number: int, slug: str, language: str, *, client=None
) -> str | None:
    import httpx

    owns_client = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        for url in neetcode_reference_urls(number, slug)[language]:
            try:
                response = client.get(url)
            except httpx.HTTPError:
                continue
            if response.status_code == 200 and response.text.strip():
                return response.text
        return None
    finally:
        if owns_client:
            client.close()


def _seed_one(
    slug: str,
    problem: Problem,
    fetch_reference: Callable[[int, str, str], str | None],
    root: Path | None,
    report: SeedReport,
) -> None:
    directory = catalog.save_problem(problem, root=root)

    got_any_reference = False
    for language, extension in LANGUAGES.items():
        source = fetch_reference(problem.number, slug, language)
        if source:
            (directory / f"reference.{extension}").write_text(source)
            got_any_reference = True

    if not got_any_reference:
        report.missing_reference.append(slug)

    # Oracle cases need a runnable Python reference and a seed input.
    python_reference = directory / "reference.py"
    seed_args = _seed_args_from_examples(problem)
    if python_reference.exists() and seed_args:
        cases = generate_oracle_cases(problem, python_reference, seed_args)
        if cases:
            catalog.save_tests(slug, cases, root=root)

    report.added.append(slug)


def _seed_args_from_examples(problem: Problem) -> dict | None:
    """Parse the first example's input into an argument dict.

    Returns None when the example cannot be parsed, in which case the
    problem is seeded without oracle cases rather than with wrong ones.
    """
    import json

    if not problem.examples:
        return None

    text = problem.examples[0].input_text
    args: dict = {}
    for spec in problem.params:
        marker = f"{spec.name} = "
        if marker not in text:
            return None
        fragment = text.split(marker, 1)[1]
        # Cut at the next parameter assignment, if any.
        for other in problem.params:
            cut = f", {other.name} = "
            if cut in fragment:
                fragment = fragment.split(cut, 1)[0]
        try:
            args[spec.name] = json.loads(fragment.strip())
        except json.JSONDecodeError:
            return None
    return args


def seed_problems(
    slugs: list[str],
    *,
    fetch: Callable[[str], Problem],
    fetch_reference: Callable[[int, str, str], str | None],
    root: Path | None = None,
) -> SeedReport:
    report = SeedReport()
    existing = set(catalog.list_slugs(root=root))

    for slug in slugs:
        if slug in existing:
            report.skipped.append(slug)
            continue
        try:
            problem = fetch(slug)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            report.failed.append((slug, str(exc)))
            continue
        _seed_one(slug, problem, fetch_reference, root, report)

    return report
```

- [ ] **Step 5: Add the `seed` command to `algorhythm/cli.py`**

```python
@app.command()
def seed(
    list_path: Path = typer.Option(
        Path("seeds/neetcode150.txt"), help="File of LeetCode slugs, one per line."
    ),
) -> None:
    """Bulk-fetch a curated list and import reference solutions."""
    from algorhythm.catalog.fetch import fetch_question
    from algorhythm.seed import (
        fetch_reference_from_github,
        read_slug_list,
        seed_problems,
    )

    slugs = read_slug_list(list_path)
    typer.echo(f"seeding {len(slugs)} problems — this hits the network, be patient")

    report = seed_problems(
        slugs,
        fetch=fetch_question,
        fetch_reference=fetch_reference_from_github,
    )
    typer.echo(report.render())
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_seed.py -v`
Expected: PASS — 13 passed

- [ ] **Step 7: Run the whole suite and a smoke check**

```bash
python -m pytest -v
algorhythm --help
algorhythm list
```

Expected: all tests pass; `--help` lists `review`, `add`, `list`, `stats`, `seed`.

- [ ] **Step 8: Commit**

```bash
git add algorhythm/seed.py algorhythm/cli.py seeds/ tests/test_seed.py
git commit -m "feat(seed): bulk library seeding with reference import

Nothing aborts the run — a failed fetch or missing reference is recorded
and seeding continues. The report is the deliverable: it names exactly
which problems need a hand-written reference before their reviews mean
anything."
```

---

## Appendix: spec coverage

| Spec section | Tasks |
|---|---|
| 2. Core loop | 13, 14 |
| 4. Architecture | all |
| 5.1 Problem content on disk | 4 |
| 5.2 SQLite schema | 2 |
| 6.1 Fetching from LeetCode | 5, 15 |
| 6.2 Reference solutions | 15 |
| 6.3 Company tags | 4 (fields + provenance), 15 (left empty — see below) |
| 6.4 Images / ASCII | 6, 7, 12 |
| 7.1 Test contents | 10 |
| 7.2 Test performance | 8, 9 |
| 8. Reviewer | 11 |
| 9. Scheduling | 1, 3 |
| 10.1 Queue and grading TUI | 14 |
| 10.2 nvim rep | 12 |
| 10.3 Language selection | 13, 14 |
| 11. Failure modes | 8, 9, 11, 13 |
| 12. Testing strategy | all |

**Deliberately not implemented in v1:**

- **Company tag import (spec 6.3).** The model, storage, and provenance fields exist (Task 4) and the UI renders them (Task 12), but nothing populates them — the public mirrors are stale scrapes of varying quality, and wiring one in is a half-hour job once you pick a source you trust. Until then the field is empty rather than wrong.
- **Daily-cap rollover as an explicit mechanism (spec 9).** Overflow rolls forward implicitly: anything not reached today is still overdue tomorrow and sorts to the front. No separate state is needed.
