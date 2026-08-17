"""One rep, start to finish.

Dependencies are injected rather than imported so the whole loop is
testable without nvim, Ollama, or a filesystem.

The governing rule from the spec is enforced here: nothing blocks the SRS
loop. A dead reviewer, a missing reference, and a compile error all still
reach the grading step.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    language: str = "python"
    # Reaches the ReviewRequest and nothing else. Deliberately not a
    # `prepare` argument: the editor always opens on the stub, and wiring
    # this into both is how the grade stopped meaning anything.
    load_previous_attempt: Callable[[str, str], str | None] = (
        lambda slug, lang: None
    )


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
    source: str = ""
    abandoned: bool = False


def run_rep(item: QueueItem, deps: RepDeps) -> RepOutcome:
    started = deps.now()
    problem = deps.load_problem(item.slug)
    language = deps.language

    # Always the stub, however many times this problem has been seen. The
    # grade is a statement about recall, and there is nothing to recall
    # from a buffer that already contains last time's answer.
    workspace = deps.prepare(
        problem, language, deps.stub_source(item.slug, language)
    )
    deps.launch(workspace)

    source = workspace.solution_path.read_text()

    try:
        run_result = deps.run_tests(problem, workspace, deps.load_tests(item.slug))
    except Exception as exc:  # noqa: BLE001 - reported to the user, never fatal
        # Everything the runners can throw lands here: FileNotFoundError when
        # clang++ is not on PATH, CodegenError for a value the canonical form
        # cannot express, an OSError launching the Python harness. By this
        # point nvim has already closed, so raising would throw away a
        # finished rep — the governing rule says the user still gets to grade.
        run_result = RunResult(
            compile_error=str(exc) or f"{type(exc).__name__} while running the tests"
        )

    try:
        review = deps.reviewer.review(
            ReviewRequest(
                problem=problem,
                language=language,
                solution_source=source,
                reference_source=deps.reference_source(item.slug, language),
                run_result=run_result,
                previous_source=deps.load_previous_attempt(item.slug, language),
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
        source=source,
        abandoned=grade is None,
    )


def persist(outcome: RepOutcome, repo: Repository, now: datetime) -> None:
    """Write everything this rep produced, or nothing at all.

    All persistence lives here rather than in `run_rep` because this is the
    only point at which the rep is known not to have been abandoned. Writing
    the attempt mid-rep would leave rows behind for reps the user declined
    to grade, contradicting the spec's failure-mode contract.
    """
    if outcome.abandoned or outcome.grade is None:
        return

    existing = repo.get_schedule(outcome.slug)
    before = existing.state if existing else outcome.state_before
    after = apply_grade(before, outcome.grade)

    # One rep is one unit of state: the review row, the advanced schedule,
    # and the attempt either all land or none do.
    with repo.transaction():
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

        repo.record_attempt(outcome.slug, now, outcome.language, outcome.source)
