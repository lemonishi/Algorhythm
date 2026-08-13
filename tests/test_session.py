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
