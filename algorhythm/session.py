"""One rep, start to finish.

Dependencies are injected rather than imported so the whole loop is
testable without nvim, Ollama, or a filesystem.

The governing rule from the spec is enforced here: nothing blocks the SRS
loop. A dead reviewer, a missing reference, and a compile error all still
reach the grading step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from algorhythm.reviewer.protocol import (
    Review,
    ReviewerUnavailable,
    ReviewRequest,
)
from algorhythm.runner.harness import RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import Grade, due_at, review as apply_grade
from algorhythm.store.repository import Repository, ReviewRecord, ScheduleRow


@dataclass
class RepDeps:
    load_problem: Callable[[str], Any]
    load_tests: Callable[[str], list]
    reference_source: Callable[[str, str], str | None]
    stub_source: Callable[[str, str], str]
    prepare: Callable[..., Any]
    launch: Callable[[Any], int]
    run_tests: Callable[..., RunResult]
    reviewer: Any
    now: Callable[[], datetime]
    ask_grade: Callable[[Review | None, RunResult], Grade | None]
    record_attempt: Callable[[str, str, str], None]
    load_previous_attempt: Callable[[str, str], str | None] = lambda slug, lang: None
    language: str = "python"


@dataclass(frozen=True)
class RepOutcome:
    slug: str
    language: str
    run_result: RunResult
    review: Review | None
    grade: Grade | None
    proposed_grade: Grade | None
    elapsed_ms: int
    state_before: Any
    abandoned: bool = False


def run_rep(item: QueueItem, deps: RepDeps) -> RepOutcome:
    started = deps.now()
    problem = deps.load_problem(item.slug)
    language = deps.language

    workspace = deps.prepare(
        problem,
        language,
        deps.stub_source(item.slug, language),
        deps.load_previous_attempt(item.slug, language),
    )
    deps.launch(workspace)

    source = workspace.solution_path.read_text()
    deps.record_attempt(item.slug, source, language)

    run_result = deps.run_tests(problem, workspace, deps.load_tests(item.slug))

    try:
        review = deps.reviewer.review(
            ReviewRequest(
                problem=problem,
                language=language,
                solution_source=source,
                reference_source=deps.reference_source(item.slug, language),
                run_result=run_result,
            )
        )
    except ReviewerUnavailable:
        review = None  # the loop continues; the user grades it unaided

    grade = deps.ask_grade(review, run_result)
    finished = deps.now()

    return RepOutcome(
        slug=item.slug,
        language=language,
        run_result=run_result,
        review=review,
        grade=grade,
        proposed_grade=review.proposed_grade if review else None,
        elapsed_ms=int((finished - started).total_seconds() * 1000),
        state_before=item.state,
        abandoned=grade is None,
    )


def persist(outcome: RepOutcome, repo: Repository, now: datetime) -> None:
    """Write the review row and reschedule. A no-op for an abandoned rep."""
    if outcome.abandoned or outcome.grade is None:
        return

    existing = repo.get_schedule(outcome.slug)
    before = existing.state if existing else outcome.state_before
    after = apply_grade(before, outcome.grade)

    repo.record_review(
        ReviewRecord(
            slug=outcome.slug,
            reviewed_at=now,
            grade=outcome.grade,
            proposed_grade=outcome.proposed_grade,
            interval_before=before.interval_days,
            interval_after=after.interval_days,
            ease_before=before.ease,
            ease_after=after.ease,
            elapsed_ms=outcome.elapsed_ms,
            tests_passed=outcome.run_result.passed,
            tests_total=outcome.run_result.total,
            language=outcome.language,
            model=outcome.review.model if outcome.review else None,
            review_text=outcome.review.text if outcome.review else None,
        )
    )

    repo.upsert_schedule(
        ScheduleRow(
            slug=outcome.slug,
            due_at=due_at(after, now),
            state=after,
            last_grade=outcome.grade,
            last_reviewed_at=now,
        )
    )
