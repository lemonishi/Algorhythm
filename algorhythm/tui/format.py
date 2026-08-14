"""Pure formatting helpers. No Textual imports, so these stay trivially
testable."""

from __future__ import annotations

from datetime import datetime, timezone

from algorhythm.runner.harness import CaseStatus, RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import Grade

GRADE_ORDER = (Grade.AGAIN, Grade.HARD, Grade.GOOD, Grade.EASY)
DEFAULT_GRADE = Grade.GOOD


def format_queue_row(
    item: QueueItem,
    title: str,
    difficulty: str,
    *,
    now: datetime | None = None,
) -> str:
    if item.is_new:
        marker = "new"
    else:
        moment = now or datetime.now(tz=timezone.utc)
        overdue_days = max(0, (moment - item.due_at).days)
        marker = f"{overdue_days}d late" if overdue_days else "due"
    return f"{marker:>9}  {difficulty:<6}  {title}"


def format_results(result: RunResult) -> str:
    if result.compile_error:
        return f"compile error\n\n{result.compile_error}"

    lines = [result.summary]
    for case in result.cases:
        if case.status is CaseStatus.PASS:
            continue
        lines.append(f"\n{case.id}: {case.status.value}")
        if case.status is CaseStatus.FAIL:
            lines.append(f"  expected {case.expected!r}")
            lines.append(f"  actual   {case.actual!r}")
        elif case.error:
            lines.append(f"  {case.error.strip().splitlines()[-1]}")
    return "\n".join(lines)


def grade_choices(proposed: Grade | None) -> list[tuple[Grade, bool]]:
    """Anki's four buttons, with exactly one preselected."""
    selected = proposed or DEFAULT_GRADE
    return [(grade, grade is selected) for grade in GRADE_ORDER]
