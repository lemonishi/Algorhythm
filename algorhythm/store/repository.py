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
