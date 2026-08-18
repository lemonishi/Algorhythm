"""The factual account of what changed since the last rep.

Computed, never generated. A 3B model asked to compare two attempts got the
direction backwards two runs in three — it called a rewrite from a working
hash map to `return [0, 0]` an improvement. A sentence about your own
history has to be true, and these facts are already in the database.
"""

from datetime import datetime, timedelta, timezone

from algorhythm.reviewer.history import ReviewSummary, describe_change
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.sm2 import Grade

NOW = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


def result(passed: int, total: int) -> RunResult:
    return RunResult(
        cases=[
            CaseResult(
                id=f"c{i}",
                status=CaseStatus.PASS if i < passed else CaseStatus.FAIL,
            )
            for i in range(total)
        ]
    )


def summary(passed=5, total=5, grade=Grade.GOOD, days_ago=4) -> ReviewSummary:
    return ReviewSummary(
        reviewed_at=NOW - timedelta(days=days_ago),
        grade=grade,
        tests_passed=passed,
        tests_total=total,
    )


def test_a_first_rep_has_nothing_to_say():
    assert describe_change(None, result(5, 5), NOW) is None


def test_it_reports_both_test_outcomes():
    line = describe_change(summary(5, 5), result(0, 5), NOW)
    assert "5/5" in line and "0/5" in line


def test_a_regression_is_named_as_one():
    """The case the model called an improvement."""
    line = describe_change(summary(5, 5), result(0, 5), NOW)
    assert "fewer" in line.lower() or "regress" in line.lower()


def test_an_improvement_is_named_as_one():
    line = describe_change(summary(2, 5), result(5, 5), NOW)
    assert "more" in line.lower() or "improv" in line.lower()


def test_the_same_outcome_is_not_dressed_up_as_progress():
    line = describe_change(summary(5, 5), result(5, 5), NOW)
    assert "fewer" not in line.lower()
    assert "more" not in line.lower()


def test_it_says_how_long_ago_and_what_you_graded_it():
    line = describe_change(summary(5, 5, Grade.HARD, days_ago=4), result(5, 5), NOW)
    assert "4 days ago" in line
    assert "hard" in line


def test_yesterday_is_not_one_days_ago():
    line = describe_change(summary(days_ago=1), result(5, 5), NOW)
    assert "1 days" not in line


def test_a_previous_rep_with_no_recorded_tests_says_only_what_it_knows():
    """Older rows predate test counts; inventing a comparison is the bug
    this module exists to avoid."""
    line = describe_change(
        ReviewSummary(NOW - timedelta(days=2), Grade.GOOD, None, None),
        result(5, 5),
        NOW,
    )
    assert "2 days ago" in line
    assert "/" not in line.split("graded")[0] or "None" not in line


def test_a_problem_with_no_tests_does_not_compare_counts():
    line = describe_change(summary(5, 5), RunResult(cases=[]), NOW)
    assert "0/0" not in line
