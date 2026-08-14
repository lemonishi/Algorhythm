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
