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


def held_back_by_new_cap(
    repo: Repository,
    catalog_slugs: list[str],
    config: QueueConfig,
    queue: list[QueueItem],
) -> bool:
    """Whether `new_per_day` alone is what made today's queue short.

    The two caps are independent, and `daily_cap` is the one people reach
    for. Raising it on an all-new library changes nothing at all, because
    the new cap is what is binding — so the queue stays exactly as short
    with no indication why. Answering that question needs all three facts
    at once: the cap was reached, the overall cap was not, and there are
    still unseen problems left to introduce.
    """
    introduced = sum(1 for item in queue if item.is_new)
    if introduced < config.new_per_day or len(queue) >= config.daily_cap:
        return False
    return len(repo.unseen(catalog_slugs, limit=introduced + 1)) > introduced
