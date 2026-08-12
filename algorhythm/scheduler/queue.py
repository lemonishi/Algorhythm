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
