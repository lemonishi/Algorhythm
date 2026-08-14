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

    def __post_init__(self) -> None:
        # `daily_cap` reaches SQLite as a LIMIT, and SQLite reads a negative
        # LIMIT as unbounded — so an unvalidated -1 quietly serves the entire
        # overdue library, defeating the hard ceiling in spec 9.
        if self.daily_cap < 1:
            raise ValueError(f"daily_cap must be at least 1, got {self.daily_cap}")
        if self.new_per_day < 0:
            raise ValueError(
                f"new_per_day cannot be negative, got {self.new_per_day}"
            )


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
