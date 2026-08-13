"""The swap seam. Everything downstream depends on `Reviewer`, not on
Ollama, so replacing the model — or adding the v2 hint agent — is a new
implementation rather than a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from algorhythm.catalog.models import Problem
from algorhythm.runner.harness import RunResult
from algorhythm.scheduler.sm2 import Grade


class ReviewerUnavailable(Exception):
    """The reviewer could not be reached. Callers must degrade gracefully:
    the rep still finishes and the user grades it manually."""


@dataclass(frozen=True)
class ReviewRequest:
    problem: Problem
    language: str
    solution_source: str
    reference_source: str | None
    run_result: RunResult


@dataclass(frozen=True)
class Review:
    text: str
    proposed_grade: Grade | None = None
    grade_reason: str | None = None
    model: str | None = None


class Reviewer(Protocol):
    def review(self, request: ReviewRequest) -> Review: ...
