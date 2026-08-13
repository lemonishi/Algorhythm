import pytest

from algorhythm.reviewer.protocol import Review
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.sm2 import Grade
from algorhythm.tui.app import GradeScreen

PASSING = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.PASS)])


@pytest.mark.asyncio
async def test_enter_accepts_the_proposed_grade():
    review = Review(text="Looks right.", proposed_grade=Grade.HARD, model="fake")
    app = GradeScreen.host(review, PASSING)
    async with app.run_test() as pilot:
        await pilot.press("enter")
    assert app.result is Grade.HARD


@pytest.mark.asyncio
async def test_arrow_keys_override_the_proposal():
    review = Review(text="x", proposed_grade=Grade.HARD, model="fake")
    app = GradeScreen.host(review, PASSING)
    async with app.run_test() as pilot:
        await pilot.press("right", "enter")
    assert app.result is Grade.GOOD


@pytest.mark.asyncio
async def test_escape_abandons_the_rep():
    app = GradeScreen.host(None, PASSING)
    async with app.run_test() as pilot:
        await pilot.press("escape")
    assert app.result is None


@pytest.mark.asyncio
async def test_review_text_is_displayed():
    review = Review(text="Use a hash map.", proposed_grade=Grade.GOOD, model="fake")
    app = GradeScreen.host(review, PASSING)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "hash map" in app.screen_text().lower()


@pytest.mark.asyncio
async def test_missing_review_shows_an_explanation_not_a_blank_pane():
    app = GradeScreen.host(None, PASSING)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "unavailable" in app.screen_text().lower()
