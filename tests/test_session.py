import sqlite3
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
        prepare=lambda p, lang, stub: FakeWorkspace(),
        launch=lambda ws: 0,
        run_tests=lambda p, ws, cases: PASSING,
        reviewer=FakeReviewer(),
        now=lambda: NOW,
        ask_grade=lambda review, run, changed=None: Grade.GOOD,
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
    outcome = run_rep(item(), deps(reviewer=reviewer, ask_grade=lambda r, s, c=None: Grade.HARD))
    assert outcome.proposed_grade is Grade.EASY
    assert outcome.grade is Grade.HARD


def test_rep_measures_elapsed_time():
    clock = iter([NOW, NOW.replace(minute=25)])
    outcome = run_rep(item(), deps(now=lambda: next(clock)))
    assert outcome.elapsed_ms == 25 * 60 * 1000


def test_a_repeat_rep_starts_from_the_stub():
    """Every rep begins from a blank stub, first time or fiftieth.

    Handing back the last answer removes the thing being measured: the
    grade is supposed to say how well the solution was recalled, and there
    is nothing to recall when it is already in the buffer.
    """
    seen = {}

    def prepare(p, lang, stub):
        seen["stub"] = stub
        return FakeWorkspace()

    run_rep(item(is_new=False), deps(prepare=prepare))
    assert seen["stub"] == "class Solution: pass"


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

    def ask(review, run, changed=None):
        asked.append(review)
        return Grade.HARD

    run_rep(item(), deps(reviewer=reviewer, ask_grade=ask))
    assert asked == [None]


def test_missing_reference_still_produces_a_review():
    outcome = run_rep(item(), deps(reference_source=lambda slug, lang: None))
    assert outcome.review is not None


def test_declining_to_grade_marks_the_rep_abandoned():
    outcome = run_rep(item(), deps(ask_grade=lambda review, run, changed=None: None))
    assert outcome.abandoned is True
    assert outcome.grade is None


def test_a_runner_that_raises_does_not_destroy_the_rep():
    """`clang++` missing from PATH makes subprocess.run raise
    FileNotFoundError. That happens after nvim has closed, so a traceback
    here costs the user 20-45 minutes of work — exactly what spec 11 exists
    to prevent."""

    def explode(problem, workspace, cases):
        raise FileNotFoundError(2, "No such file or directory: 'clang++'")

    outcome = run_rep(item(), deps(run_tests=explode))
    assert outcome.grade is Grade.GOOD
    assert outcome.abandoned is False
    assert "clang++" in outcome.run_result.compile_error


def test_a_runner_that_raises_still_gets_reviewed_and_graded():
    asked = []

    def explode(problem, workspace, cases):
        raise RuntimeError("cannot express set in the canonical form")

    run_rep(
        item(),
        deps(
            run_tests=explode,
            ask_grade=lambda review, run, changed=None: asked.append(run) or Grade.HARD,
        ),
    )
    assert len(asked) == 1
    assert asked[0].compile_error is not None


def test_a_runner_raising_a_message_less_exception_still_says_something():
    def explode(problem, workspace, cases):
        raise RuntimeError()

    outcome = run_rep(item(), deps(run_tests=explode))
    assert outcome.run_result.compile_error


def test_compile_error_still_reaches_the_grading_step():
    broken = RunResult(compile_error="SyntaxError")
    outcome = run_rep(item(), deps(run_tests=lambda p, ws, c: broken))
    assert outcome.run_result.compile_error == "SyntaxError"
    assert outcome.grade is Grade.GOOD


# -- persistence ----------------------------------------------------------

def test_persist_writes_a_review_row_and_schedules_the_next_rep():
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        outcome = run_rep(item(), deps())
        persist(outcome, repo, NOW)

        assert repo.counts()["reviews"] == 1
        row = repo.get_schedule("two-sum")
        assert row is not None
        assert row.state.reps == 1
        assert row.due_at > NOW
    finally:
        conn.close()


def test_persist_applies_sm2_from_the_existing_state():
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
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
    finally:
        conn.close()


def test_persist_ignores_an_abandoned_rep():
    """The governing rule extends to attempts: nvim exiting without saving
    must leave nothing in the database at all, not just no review/schedule."""
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        outcome = run_rep(item(), deps(ask_grade=lambda r, s, c=None: None))
        persist(outcome, repo, NOW)
        assert repo.counts()["reviews"] == 0
        assert repo.counts()["attempts"] == 0
        assert repo.get_schedule("two-sum") is None
    finally:
        conn.close()


def test_persist_records_the_attempt_for_a_graded_rep():
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        outcome = run_rep(item(), deps())
        persist(outcome, repo, NOW)

        assert repo.counts()["attempts"] == 1
        row = conn.execute("SELECT source FROM attempts").fetchone()
        assert row["source"] == outcome.source == "class Solution: pass"
    finally:
        conn.close()


def test_persist_writes_all_three_rows_or_none_of_them():
    """A failure between the review row and the schedule update leaves a card
    that stays due, gets re-served, and is double-counted in the log FSRS
    would later train on."""
    conn = connect(":memory:")
    try:
        repo = Repository(conn)

        def explode(row):
            raise sqlite3.OperationalError("database is locked")

        repo.upsert_schedule = explode

        outcome = run_rep(item(), deps())
        with pytest.raises(sqlite3.OperationalError):
            persist(outcome, repo, NOW)

        assert repo.counts() == {"scheduled": 0, "reviews": 0, "attempts": 0}
    finally:
        conn.close()


def test_persist_records_the_post_edit_source_not_the_seeded_stub():
    """What lands in `attempts` is what the workspace held when nvim
    closed, not the stub the rep started from."""
    edited = "class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]"

    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        outcome = run_rep(
            item(),
            deps(
                stub_source=lambda slug, lang: "class Solution: pass",
                prepare=lambda p, lang, stub: FakeWorkspace(edited),
            ),
        )
        persist(outcome, repo, NOW)

        row = conn.execute("SELECT source FROM attempts").fetchone()
        assert row["source"] == edited
        assert row["source"] != "class Solution: pass"
    finally:
        conn.close()


def test_the_previous_attempt_reaches_the_reviewer():
    """It is what makes a 'since last time' remark possible."""
    seen = {}

    class Capturing:
        def review(self, request):
            seen["previous"] = request.previous_source
            return Review(text="ok", proposed_grade=Grade.GOOD, model="fake")

    run_rep(
        item(is_new=False),
        deps(
            reviewer=Capturing(),
            load_previous_attempt=lambda slug, lang: "old code",
        ),
    )
    assert seen["previous"] == "old code"


def test_the_previous_attempt_never_reaches_the_editor():
    """The buffer opens on the stub, whatever the reviewer is given.

    These two travel together and must not: showing last time's answer
    before the rep is the thing that made the grade meaningless.
    """
    seen = {}

    def prepare(p, lang, stub):
        seen["stub"] = stub
        return FakeWorkspace()

    run_rep(
        item(is_new=False),
        deps(prepare=prepare, load_previous_attempt=lambda slug, lang: "old code"),
    )
    assert seen["stub"] == "class Solution: pass"
