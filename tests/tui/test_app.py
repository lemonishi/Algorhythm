import dataclasses
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Problem
from algorhythm.reviewer.protocol import Review
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import NEW, Grade
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository
from textual.widgets import Label, Static

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


def test_the_previous_attempt_is_wired_to_the_reviewer_not_the_editor(monkeypatch):
    """Both halves of the rule, in the place they are wired together.

    The reviewer needs the previous attempt to say what changed; the editor
    must never see it, or the buffer stops being blank and the grade stops
    being a statement about recall. `prepare` taking three arguments is what
    makes the second half true by construction.
    """
    import inspect

    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        monkeypatch.setattr(tui_app.catalog, "load_problem", _problem)
        item = QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)

        captured = _capture_deps(monkeypatch, repo, [item])

        assert captured["load_previous_attempt"] == repo.last_attempt_source
        prepare_params = inspect.signature(captured["prepare"]).parameters
        assert list(prepare_params) == ["problem", "lang", "stub"]
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


# -- vim motions ------------------------------------------------------------


async def test_j_and_k_move_the_queue_cursor():
    from textual.widgets import ListView

    from algorhythm.tui.app import QueueScreen

    app = QueueScreen(["a", "b", "c"])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(ListView).index == 0
        await pilot.press("j")
        assert app.query_one(ListView).index == 1
        await pilot.press("j")
        assert app.query_one(ListView).index == 2
        await pilot.press("k")
        assert app.query_one(ListView).index == 1


async def test_l_opens_the_highlighted_problem():
    """`l` moves into a thing, the way it does everywhere else in vim."""
    from algorhythm.tui.app import QueueScreen

    app = QueueScreen(["a", "b", "c"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("l")
    assert app.chosen == 1


async def test_enter_still_opens_the_highlighted_problem():
    """The vim keys are additions, not replacements."""
    from algorhythm.tui.app import QueueScreen

    app = QueueScreen(["a", "b"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("enter")
    assert app.chosen == 1


async def test_h_leaves_the_queue():
    from algorhythm.tui.app import QueueScreen

    app = QueueScreen(["a", "b"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("h")
    assert app.chosen is None


async def test_h_and_l_move_between_grades():
    """The grade options are a row, so h and l are the motions that fit."""
    run_result = RunResult(cases=[])
    screen = tui_app.GradeScreen(None, run_result)
    async with screen.run_test() as pilot:
        await pilot.pause()
        start = screen._index
        await pilot.press("l")
        assert screen._index == (start + 1) % 4
        await pilot.press("h")
        assert screen._index == start


# -- picking topics from inside the queue -----------------------------------

TOPIC_COUNTS = {"Array": 74, "Graph Theory": 8, "Tree": 13}


async def test_f_asks_the_queue_to_open_the_topic_picker():
    from algorhythm.tui.app import QueueScreen

    app = QueueScreen(["a", "b"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f")
    assert app.wants_filter is True
    assert app.chosen is None


async def test_the_active_topics_are_shown_on_the_queue():
    """Otherwise a filtered queue is indistinguishable from a short one."""
    from algorhythm.tui.app import QueueScreen

    app = QueueScreen(["a"], topics=["Graph Theory"])
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = " ".join(str(w.render()) for w in app.query(Static))
        assert "Graph Theory" in rendered


async def test_space_toggles_a_topic_and_enter_applies_the_selection():
    from algorhythm.tui.app import TopicScreen

    app = TopicScreen(TOPIC_COUNTS, [])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")       # Array, the most common, is first
        await pilot.press("j")
        await pilot.press("space")       # Tree
        await pilot.press("enter")
    assert sorted(app.result) == ["Array", "Tree"]


async def test_enter_with_nothing_toggled_takes_the_highlighted_topic():
    """Picking one topic is the common case; it should not need a toggle."""
    from algorhythm.tui.app import TopicScreen

    app = TopicScreen(TOPIC_COUNTS, [])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("enter")
    assert app.result == ["Tree"]


async def test_escape_leaves_the_filter_untouched():
    """Cancel and 'no topics' are different answers and must not collapse."""
    from algorhythm.tui.app import TopicScreen

    app = TopicScreen(TOPIC_COUNTS, ["Array"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
    assert app.result is None


async def test_c_clears_the_filter_entirely():
    from algorhythm.tui.app import TopicScreen

    app = TopicScreen(TOPIC_COUNTS, ["Array"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
    assert app.result == []


async def test_an_already_active_topic_starts_toggled_on():
    from algorhythm.tui.app import TopicScreen

    app = TopicScreen(TOPIC_COUNTS, ["Tree"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
    assert app.result == ["Tree"]


async def test_topics_are_listed_with_their_counts():
    from algorhythm.tui.app import TopicScreen

    app = TopicScreen(TOPIC_COUNTS, [])
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = " ".join(str(w.render()) for w in app.query(Label))
        assert "Array" in rendered and "74" in rendered


def test_choosing_topics_rebuilds_the_queue(monkeypatch):
    """The point of filtering here is a different queue, not a shorter view.

    Only rebuilding can bring in problems today's queue never contained —
    the whole reason to pick a topic is to practise something the daily
    selection did not offer.
    """
    asked: list[list[str]] = []
    screens: list[list[str]] = []

    runs = iter([True, False])

    def fake_queue_run(self):
        screens.append(list(self._rows))
        if next(runs):
            self.wants_filter = True
        else:
            self.chosen = None

    def fake_topic_run(self):
        self.result = ["Graph Theory"]

    monkeypatch.setattr(tui_app.QueueScreen, "run", fake_queue_run)
    monkeypatch.setattr(tui_app.TopicScreen, "run", fake_topic_run)
    monkeypatch.setattr(tui_app.catalog, "all_topics", lambda: {"Graph Theory": 8})
    # Title follows the slug so the rendered rows say which queue is shown.
    monkeypatch.setattr(
        tui_app.catalog,
        "load_problem",
        lambda slug: dataclasses.replace(_problem(slug), title=slug),
    )

    def rebuild(topics):
        asked.append(topics)
        return [QueueItem(slug="clone-graph", is_new=True, due_at=None, state=NEW)]

    conn = connect(":memory:")
    try:
        tui_app.run_queue(
            [QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)],
            Repository(conn),
            rebuild=rebuild,
        )
    finally:
        conn.close()

    assert asked == [["Graph Theory"]]
    assert "two-sum" in screens[0][0]
    assert "clone-graph" in screens[1][0]


def test_cancelling_the_topic_picker_leaves_the_queue_alone(monkeypatch):
    rebuilt: list = []
    runs = iter([True, False])

    def fake_queue_run(self):
        if next(runs):
            self.wants_filter = True
        else:
            self.chosen = None

    monkeypatch.setattr(tui_app.QueueScreen, "run", fake_queue_run)
    monkeypatch.setattr(tui_app.TopicScreen, "run", lambda self: None)
    monkeypatch.setattr(tui_app.catalog, "all_topics", lambda: {"Graph Theory": 8})
    monkeypatch.setattr(tui_app.catalog, "load_problem", lambda slug: _problem(slug))

    conn = connect(":memory:")
    try:
        tui_app.run_queue(
            [QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)],
            Repository(conn),
            rebuild=lambda topics: rebuilt.append(topics) or [],
        )
    finally:
        conn.close()

    assert rebuilt == []


async def test_a_toggled_topic_is_visibly_marked():
    """The marker has to survive rendering, not just be in the string.

    `[x]` is Rich markup: it parses as a style tag and is stripped, so the
    row renders identically whether the topic is selected or not and there
    is no way to see what you have chosen.
    """
    from algorhythm.tui.app import TopicScreen

    app = TopicScreen(TOPIC_COUNTS, [])
    async with app.run_test() as pilot:
        await pilot.pause()
        before = [str(w.render()) for w in app.query("ListItem Label")]
        await pilot.press("space")
        after = [str(w.render()) for w in app.query("ListItem Label")]

    assert after[0].startswith(TopicScreen.SELECTED), after[0]
    assert before[0].startswith(TopicScreen.UNSELECTED), before[0]
    assert "Array" in after[0]
    # The unselected rows are untouched.
    assert before[1] == after[1]


async def test_the_grade_screen_shows_the_since_last_note():
    """It is the context you want while deciding a grade: whether this rep
    was better than the last one is most of what the grade is saying."""
    review = Review(
        text="Hash map, matches the reference.",
        proposed_grade=Grade.GOOD,
        model="fake",
    )
    app = tui_app.GradeScreen(
        review, RunResult(cases=[]), "Last seen 4 days ago, tests 5/5 → 0/5."
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = " ".join(str(w.render()) for w in app.query(Static))
    assert "5/5 → 0/5" in rendered
    assert "Hash map, matches the reference." in rendered


async def test_the_grade_screen_omits_the_heading_without_a_note():
    app = tui_app.GradeScreen(
        Review(text="Fine.", proposed_grade=Grade.GOOD, model="fake"),
        RunResult(cases=[]),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = " ".join(str(w.render()) for w in app.query(Static))
    assert "Since last time" not in rendered
