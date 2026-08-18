"""What changed since the last rep, stated as fact.

Computed rather than generated, deliberately. Asked to compare this
attempt with the previous one, a 3B model got the direction backwards two
runs in three: it called a rewrite from a working hash map to
`return [0, 0]` an improvement, and on another run reported no change at
all. Five prompt variants did not fix it — the instruction in the system
prompt, the field required by the response schema, the field generated
first, an imperative beside the code, and a unified diff with the test
counts spelled out.

A sentence about the reader's own history is worth having only if it is
true, and everything needed is already in the reviews table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from algorhythm.runner.harness import RunResult
from algorhythm.scheduler.sm2 import Grade


@dataclass(frozen=True)
class ReviewSummary:
    """The previous rep of one problem, as recorded."""

    reviewed_at: datetime
    grade: Grade
    tests_passed: int | None
    tests_total: int | None


def _ago(previous: datetime, now: datetime) -> str:
    days = max((now - previous).days, 0)
    return {0: "earlier today", 1: "yesterday"}.get(days, f"{days} days ago")


def describe_change(
    previous: ReviewSummary | None, run_result: RunResult, now: datetime
) -> str | None:
    """One sentence on how this rep compares with the last, or None.

    None on a first rep: there is nothing to compare, and a heading with
    nothing under it is worse than no heading.
    """
    if previous is None:
        return None

    parts = [f"Last seen {_ago(previous.reviewed_at, now)}"]

    # Both counts, or neither. Rows written before test counts were
    # recorded have None, and a comparison against a missing number is the
    # kind of invention this module exists to avoid.
    comparable = (
        previous.tests_total
        and previous.tests_total > 0
        and run_result.total > 0
        and previous.tests_passed is not None
    )
    if comparable:
        before = f"{previous.tests_passed}/{previous.tests_total}"
        after = f"{run_result.passed}/{run_result.total}"
        parts.append(f"tests {before} → {after}")
        if run_result.passed > previous.tests_passed:
            parts.append("more passing than last time")
        elif run_result.passed < previous.tests_passed:
            parts.append("fewer passing than last time")

    parts.append(f"you graded it {previous.grade.value}")
    return ", ".join(parts) + "."
