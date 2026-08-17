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
def test_same_second_rows_order_chronologically_despite_the_omitted_micros(repo):
    second = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
    repo.upsert_schedule(_row("half", second.replace(microsecond=500_000)))
    repo.upsert_schedule(_row("on-the-second", second))  # isoformat omits ".000000"
    repo.upsert_schedule(_row("a-micro-later", second.replace(microsecond=1)))

    order = [r.slug for r in repo.due(second + timedelta(seconds=1), limit=10)]
    assert order == ["on-the-second", "a-micro-later", "half"]


def test_the_shortened_form_sorts_before_the_long_one(repo):
    """The mechanism itself, pinned directly rather than via a query."""
    from algorhythm.store.repository import _iso

    second = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
    assert _iso(second) == "2026-08-12T09:00:00+00:00"
    assert _iso(second.replace(microsecond=1)) == "2026-08-12T09:00:00.000001+00:00"
    assert _iso(second) < _iso(second.replace(microsecond=1))


def test_most_recent_review_in_the_same_second_is_the_one_returned(repo):
    """The DESC ordering has to agree with `_iso`, or the language of the
    last rep is read from the wrong row whenever two land in one second."""
    second = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)
    for lang, when in (("python", second), ("cpp", second.replace(microsecond=1))):
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


def test_transaction_commits_everything_inside_it(repo):
    with repo.transaction():
        repo.record_attempt("two-sum", NOW, "python", "solution")
        repo.upsert_schedule(_row("two-sum", NOW))
    assert repo.counts() == {"scheduled": 1, "reviews": 0, "attempts": 1}


def test_transaction_rolls_back_every_write_on_failure(repo):
    """The connection is in autocommit, so without an explicit transaction
    each write lands on its own — leaving, say, a review row for a card whose
    schedule never advanced: still due, re-served, double-counted."""
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.record_attempt("two-sum", NOW, "python", "solution")
            raise RuntimeError("something failed halfway")
    assert repo.counts()["attempts"] == 0


def test_writes_after_a_rolled_back_transaction_still_work(repo):
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.record_attempt("two-sum", NOW, "python", "solution")
            raise RuntimeError("boom")
    repo.record_attempt("two-sum", NOW, "python", "second try")
    assert repo.counts()["attempts"] == 1


def test_upsert_schedule_rejects_naive_datetime(repo):
    naive = datetime(2026, 8, 12, 9, 0)
    with pytest.raises(ValueError):
        repo.upsert_schedule(_row("two-sum", naive))


def test_last_attempt_source_returns_the_most_recent_for_that_language(repo):
    """Feeds the reviewer's 'since last time' remark, nothing else.

    Same language only: comparing a Python answer against a C++ one says
    nothing useful about whether the candidate improved.
    """
    repo.record_attempt("two-sum", NOW - timedelta(days=2), "python", "first")
    repo.record_attempt("two-sum", NOW, "python", "second")
    repo.record_attempt("two-sum", NOW, "cpp", "in c++")

    assert repo.last_attempt_source("two-sum", "python") == "second"
    assert repo.last_attempt_source("two-sum", "cpp") == "in c++"
    assert repo.last_attempt_source("two-sum", "rust") is None
    assert repo.last_attempt_source("no-such-problem", "python") is None
