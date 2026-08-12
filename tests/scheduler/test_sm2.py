from datetime import datetime, timezone

import pytest

from algorhythm.scheduler.sm2 import (
    EASE_CEILING,
    EASE_FLOOR,
    NEW,
    Grade,
    SchedulingState,
    due_at,
    review,
)


def test_new_card_intervals_are_multi_day():
    """A card here costs 20-45 minutes, so no interval starts at one day
    except a lapse. These four values are the whole point of the tuning."""
    assert review(NEW, Grade.AGAIN).interval_days == 1.0
    assert review(NEW, Grade.HARD).interval_days == 2.0
    assert review(NEW, Grade.GOOD).interval_days == 3.0
    assert review(NEW, Grade.EASY).interval_days == 5.0


def test_new_card_does_not_adjust_ease():
    for grade in Grade:
        assert review(NEW, grade).ease == NEW.ease


def test_good_multiplies_by_ease():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    assert review(state, Grade.GOOD).interval_days == 25.0


def test_good_leaves_ease_unchanged():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    assert review(state, Grade.GOOD).ease == 2.5


def test_hard_uses_fixed_multiplier_and_lowers_ease():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    result = review(state, Grade.HARD)
    assert result.interval_days == 12.0
    assert result.ease == pytest.approx(2.35)


def test_easy_applies_bonus_and_raises_ease():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=0)
    result = review(state, Grade.EASY)
    assert result.interval_days == pytest.approx(32.5)
    assert result.ease == pytest.approx(2.65)


def test_again_softens_rather_than_resetting():
    """Anki resets a lapse to ~1 day. A 20-minute card can't afford that."""
    state = SchedulingState(interval_days=30.0, ease=2.5, reps=5, lapses=0)
    result = review(state, Grade.AGAIN)
    assert result.interval_days == 9.0
    assert result.ease == pytest.approx(2.3)
    assert result.lapses == 1


def test_again_never_drops_below_one_day():
    state = SchedulingState(interval_days=2.0, ease=2.5, reps=2, lapses=0)
    assert review(state, Grade.AGAIN).interval_days == 1.0


def test_ease_floors_at_minimum():
    state = SchedulingState(interval_days=10.0, ease=EASE_FLOOR, reps=9, lapses=4)
    assert review(state, Grade.AGAIN).ease == EASE_FLOOR


def test_ease_ceilings_at_maximum():
    state = SchedulingState(interval_days=10.0, ease=EASE_CEILING, reps=9, lapses=0)
    assert review(state, Grade.EASY).ease == EASE_CEILING


def test_reps_increment_on_every_grade():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=1)
    for grade in Grade:
        assert review(state, grade).reps == 4


def test_lapses_increment_only_on_again():
    state = SchedulingState(interval_days=10.0, ease=2.5, reps=3, lapses=1)
    assert review(state, Grade.AGAIN).lapses == 2
    for grade in (Grade.HARD, Grade.GOOD, Grade.EASY):
        assert review(state, grade).lapses == 1


def test_realistic_good_sequence_grows_sanely():
    """Four consecutive 'good' grades from new should land in the
    weeks-to-months range, not days and not years."""
    state = NEW
    for _ in range(4):
        state = review(state, Grade.GOOD)
    assert 40.0 < state.interval_days < 60.0


def test_due_at_offsets_from_now():
    state = SchedulingState(interval_days=3.0, ease=2.5, reps=1, lapses=0)
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    assert due_at(state, now) == datetime(2026, 8, 15, tzinfo=timezone.utc)
