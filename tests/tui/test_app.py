from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Problem
from algorhythm.reviewer.protocol import Review
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import NEW, Grade
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository
from algorhythm.tui import app as tui_app
from algorhythm.tui.app import GradeScreen

PASSING = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.PASS)])
NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _problem(slug: str) -> Problem:
    return Problem(
        slug=slug,
        number=1,
        title="Two Sum",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=[],
        return_kind="raw",
        entry_point="twoSum",
        fetched_at=NOW,
    )


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


# -- run_queue wiring -------------------------------------------------------
#
# Driving a real QueueScreen/GradeScreen end to end would mean piloting two
# nested Textual apps launched via App.run() (not run_test()), which needs a
# real terminal. That's disproportionate for checking one wire. Instead this
# stubs out everything run_queue touches except RepDeps construction, and
# checks the one thing this fix is about: that load_previous_attempt reaches
# the store rather than falling back to RepDeps' default no-op.


def test_run_queue_wires_load_previous_attempt_to_the_store(monkeypatch):
    import algorhythm.session as session_module

    conn = connect(":memory:")
    try:
        repo = Repository(conn)

        monkeypatch.setattr(tui_app.catalog, "load_problem", _problem)
        monkeypatch.setattr(
            tui_app.QueueScreen, "run", lambda self: setattr(self, "chosen", 0)
        )

        captured: dict = {}

        class CapturingRepDeps:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        def fake_run_rep(item, deps):
            raise RuntimeError("stop after capturing deps")

        monkeypatch.setattr(session_module, "RepDeps", CapturingRepDeps)
        monkeypatch.setattr(session_module, "run_rep", fake_run_rep)

        item = QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)

        with pytest.raises(RuntimeError):
            tui_app.run_queue([item], repo)

        assert "load_previous_attempt" in captured
        assert captured["load_previous_attempt"] == repo.last_attempt_source
    finally:
        conn.close()
