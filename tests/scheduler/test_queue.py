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


def test_a_non_positive_daily_cap_is_rejected():
    """SQLite reads `LIMIT -1` as unbounded, so a negative cap would serve
    the entire overdue library — the one thing spec 9's hard ceiling exists
    to prevent. A cap of zero is equally nonsense: it means 'do nothing'."""
    with pytest.raises(ValueError, match="daily_cap"):
        QueueConfig(daily_cap=-1)
    with pytest.raises(ValueError, match="daily_cap"):
        QueueConfig(daily_cap=0)


def test_a_negative_new_per_day_is_rejected():
    with pytest.raises(ValueError, match="new_per_day"):
        QueueConfig(new_per_day=-1)


def test_zero_new_per_day_is_allowed(repo):
    """'Introduce nothing new today' is a legitimate setting."""
    assert build_queue(repo, CATALOG, NOW, QueueConfig(new_per_day=0)) == []


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
