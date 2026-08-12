"""SM-2 spaced repetition, tuned for cards that cost 20-45 minutes.

Pure functions only. No I/O, no clock reads — callers pass `now`.

Deviations from Anki's defaults, all deliberate (see spec section 9):
  * No sub-day learning steps. You cannot re-solve a problem in ten minutes.
  * New cards start at 2-5 days rather than 1.
  * A lapse multiplies the interval by 0.3 instead of resetting it, because
    re-earning a 30-day interval costs hours of work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Grade(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


EASE_START = 2.5
EASE_FLOOR = 1.3
EASE_CEILING = 3.0

HARD_MULTIPLIER = 1.2
EASY_BONUS = 1.3
LAPSE_MULTIPLIER = 0.3
LAPSE_MIN_DAYS = 1.0

NEW_INTERVAL_DAYS: dict[Grade, float] = {
    Grade.AGAIN: 1.0,
    Grade.HARD: 2.0,
    Grade.GOOD: 3.0,
    Grade.EASY: 5.0,
}

EASE_DELTA: dict[Grade, float] = {
    Grade.AGAIN: -0.20,
    Grade.HARD: -0.15,
    Grade.GOOD: 0.0,
    Grade.EASY: 0.15,
}


@dataclass(frozen=True)
class SchedulingState:
    interval_days: float
    ease: float
    reps: int
    lapses: int


NEW = SchedulingState(interval_days=0.0, ease=EASE_START, reps=0, lapses=0)


def _clamp_ease(ease: float) -> float:
    return min(EASE_CEILING, max(EASE_FLOOR, ease))


def review(state: SchedulingState, grade: Grade) -> SchedulingState:
    """Return the state that results from grading `state` with `grade`."""
    if state.reps == 0:
        # First exposure: fixed intervals, ease untouched.
        interval = NEW_INTERVAL_DAYS[grade]
        ease = state.ease
    elif grade is Grade.AGAIN:
        interval = max(LAPSE_MIN_DAYS, state.interval_days * LAPSE_MULTIPLIER)
        ease = state.ease + EASE_DELTA[grade]
    elif grade is Grade.HARD:
        interval = state.interval_days * HARD_MULTIPLIER
        ease = state.ease + EASE_DELTA[grade]
    elif grade is Grade.GOOD:
        interval = state.interval_days * state.ease
        ease = state.ease
    else:  # Grade.EASY
        interval = state.interval_days * state.ease * EASY_BONUS
        ease = state.ease + EASE_DELTA[grade]

    return SchedulingState(
        interval_days=round(interval, 4),
        ease=round(_clamp_ease(ease), 4),
        reps=state.reps + 1,
        lapses=state.lapses + (1 if grade is Grade.AGAIN else 0),
    )


def due_at(state: SchedulingState, now: datetime) -> datetime:
    """When a card in `state` next becomes due."""
    return now + timedelta(days=state.interval_days)
