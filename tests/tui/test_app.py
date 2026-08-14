from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Problem
from algorhythm.reviewer.protocol import Review
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import NEW, Grade
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository
from textual.widgets import Static

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


def _capture_deps(monkeypatch, repo, items, chosen=0, **run_queue_kwargs) -> dict:
    """Drive run_queue far enough to see the RepDeps it built, then stop."""
    import algorhythm.session as session_module

    shown: list[list[str]] = []

    def fake_run(self):
        shown.append(list(self._rows))
        self.chosen = chosen

    monkeypatch.setattr(tui_app.QueueScreen, "run", fake_run)

    captured: dict = {}

    class CapturingRepDeps:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    def fake_run_rep(item, deps):
        captured["item"] = item
        raise RuntimeError("stop after capturing deps")

    monkeypatch.setattr(session_module, "RepDeps", CapturingRepDeps)
    monkeypatch.setattr(session_module, "run_rep", fake_run_rep)

    with pytest.raises(RuntimeError):
        tui_app.run_queue(items, repo, **run_queue_kwargs)
    captured["rows"] = shown
    return captured


def test_an_unloadable_problem_does_not_kill_the_session(monkeypatch):
    """load_problem ran over every remaining queue row on every iteration, so
    one malformed meta.json anywhere in today's queue crashed the loop before
    a single rep started."""
    conn = connect(":memory:")
    try:
        repo = Repository(conn)

        def load(slug):
            if slug == "corrupt":
                raise KeyError("entry_point")
            return _problem(slug)

        monkeypatch.setattr(tui_app.catalog, "load_problem", load)
        items = [
            QueueItem(slug="corrupt", is_new=True, due_at=None, state=NEW),
            QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW),
        ]

        captured = _capture_deps(monkeypatch, repo, items)

        # The broken row is announced rather than swallowed, and picking it
        # drops it so the queue moves on to a problem that does load.
        assert any("corrupt" in row for row in captured["rows"][0])
        assert captured["item"].slug == "two-sum"
    finally:
        conn.close()


def test_run_queue_wires_load_previous_attempt_to_the_store(monkeypatch):
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        monkeypatch.setattr(tui_app.catalog, "load_problem", _problem)
        item = QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)

        captured = _capture_deps(monkeypatch, repo, [item])

        assert "load_previous_attempt" in captured
        assert captured["load_previous_attempt"] == repo.last_attempt_source
    finally:
        conn.close()


def test_language_override_wins_over_the_previous_reps_language(monkeypatch):
    """Spec 10.3: `--lang` outranks history. Without the override the chain
    is `last_language` -> `reviews.language` -> `last_language` again, whose
    only fixed point is "python", so C++ is unreachable."""
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        monkeypatch.setattr(tui_app.catalog, "load_problem", _problem)
        monkeypatch.setattr(repo, "last_language", lambda slug: "python")
        item = QueueItem(slug="two-sum", is_new=False, due_at=NOW, state=NEW)

        captured = _capture_deps(monkeypatch, repo, [item], language="cpp")

        assert captured["language"] == "cpp"
    finally:
        conn.close()


def test_without_an_override_the_previous_language_is_used(monkeypatch):
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        monkeypatch.setattr(tui_app.catalog, "load_problem", _problem)
        monkeypatch.setattr(repo, "last_language", lambda slug: "cpp")
        item = QueueItem(slug="two-sum", is_new=False, due_at=NOW, state=NEW)

        captured = _capture_deps(monkeypatch, repo, [item])

        assert captured["language"] == "cpp"
    finally:
        conn.close()


def test_language_falls_back_to_python_for_a_first_rep(monkeypatch):
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        monkeypatch.setattr(tui_app.catalog, "load_problem", _problem)
        item = QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)

        captured = _capture_deps(monkeypatch, repo, [item])

        assert captured["language"] == "python"
    finally:
        conn.close()


def test_run_queue_rejects_an_unknown_language(monkeypatch):
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        monkeypatch.setattr(tui_app.catalog, "load_problem", _problem)
        item = QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)
        with pytest.raises(ValueError, match="unknown language"):
            tui_app.run_queue([item], repo, language="rust")
    finally:
        conn.close()


# -- the short-queue note ---------------------------------------------------


async def test_the_queue_screen_shows_a_note_when_given_one():
    """The note has to be inside the Textual screen.

    Anything echoed before launch is wiped: Textual takes the whole
    terminal, so a printed hint is never read.
    """
    from algorhythm.tui.app import QueueScreen

    note = "Showing 2 — `--new 2` caps how many unseen problems per day."
    app = QueueScreen(["a", "b"], note)
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = " ".join(str(w.render()) for w in app.query(Static))
        assert "--new" in rendered


async def test_the_queue_screen_has_no_note_by_default():
    from algorhythm.tui.app import QueueScreen

    app = QueueScreen(["a", "b"])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.query("#note")) == 0
